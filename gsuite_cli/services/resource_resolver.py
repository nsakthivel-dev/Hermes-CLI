"""
Global Resource Resolver and Selector for Hermes CLI.
Provides a human-friendly resource resolution and selection system across all Google Workspace APIs.
Resolution Priority:
1. NUMBER (1..N corresponding to displayed list/page)
2. ALIAS (module-specific alias stored in configuration)
3. EXACT NAME / TITLE (case-insensitive)
4. SUBSTRING / SEARCH MATCH (case-insensitive)
5. DIRECT GOOGLE RESOURCE ID
"""

from __future__ import annotations
import sys
from typing import Dict, List, Any, Optional, Tuple, Callable
from colorama import Fore, Style
from ..utils.formatters import (
    print_error,
    print_info,
    print_success,
    print_warning,
    print_key_value_pairs,
    clear_screen,
)


class ResourceResolutionError(Exception):
    """Base exception for resource resolution errors."""
    pass


class ResourceNotFoundError(ResourceResolutionError):
    """Raised when an entered resource reference cannot be resolved."""
    def __init__(self, input_val: str, available_resources: Optional[List[Dict[str, Any]]] = None, resource_type: str = "Resource"):
        self.input_val = input_val
        self.available_resources = available_resources or []
        self.resource_type = resource_type
        super().__init__(f"{resource_type} not found: {input_val}")


class AmbiguousResourceNameError(ResourceResolutionError):
    """Raised when multiple resources match the same name."""
    def __init__(self, name: str, matching_resources: List[Dict[str, Any]], resource_type: str = "Resource"):
        self.name = name
        self.matching_resources = matching_resources
        self.matches = matching_resources
        self.resource_type = resource_type
        super().__init__(f"Multiple {resource_type.lower()}s found matching '{name}'")


AmbiguousResourceError = AmbiguousResourceNameError


class AliasDeletedError(ResourceResolutionError):
    """Raised when an alias references a resource that no longer exists."""
    def __init__(self, alias: str, available_resources: Optional[List[Dict[str, Any]]] = None, resource_type: str = "Resource"):
        self.alias = alias
        self.available_resources = available_resources or []
        self.resource_type = resource_type
        super().__init__(f"Alias '{alias}' points to a {resource_type.lower()} that is no longer available.")


class GlobalResourceResolver:
    """
    Unified resource resolver, formatter, alias manager, and interactive selector
    for all Google Workspace modules.
    """

    @staticmethod
    def get_resource_title(item: Dict[str, Any], custom_field: Optional[str] = None) -> str:
        """Extract a friendly title/name from a resource dictionary."""
        if not isinstance(item, dict):
            return str(item)
        if custom_field and item.get(custom_field):
            return str(item[custom_field])
        for key in [
            'summary', 'name', 'title', 'displayName', 'subject',
            'primaryEmail', 'email', 'scriptId', 'formId', 'documentId',
            'spreadsheetId', 'id'
        ]:
            val = item.get(key)
            if val and isinstance(val, str) and val.strip():
                # For Meet/Chat spaces where name is 'spaces/123' or 'users/456'
                if key == 'name' and '/' in val and ('displayName' in item or 'space' in item):
                    continue
                return val.strip()
        return item.get('id', 'Untitled')

    @staticmethod
    def get_resource_id(item: Dict[str, Any], custom_field: Optional[str] = None) -> str:
        """Extract the canonical technical ID from a resource dictionary."""
        if not isinstance(item, dict):
            return str(item)
        if custom_field and item.get(custom_field):
            return str(item[custom_field])
        for key in ['id', 'name', 'calendarId', 'scriptId', 'documentId', 'spreadsheetId', 'formId', 'subscriptionId', 'email']:
            val = item.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()
        return str(item.get('id', ''))

    _aliases: Dict[str, Dict[str, str]] = {}

    @classmethod
    def resolve(
        cls,
        input_str: Any,
        items: Any = None,
        module: Optional[str] = None,
        resource_type: str = "Resource",
        config_manager: Optional[Any] = None,
        fetch_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        title_fn: Optional[Callable[[Dict[str, Any]], str]] = None,
        id_fn: Optional[Callable[[Dict[str, Any]], str]] = None,
        title_key: Optional[str] = None,
        id_key: Optional[str] = None,
        allow_prompt: bool = True,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Resolve user input to a resource dictionary adhering strictly to priority:
        1. NUMBER
        2. ALIAS
        3. EXACT NAME / TITLE
        4. SUBSTRING MATCH
        5. DIRECT RESOURCE ID
        """
        # Allow calling as resolve(items, input_str) or resolve(input_str, items)
        if isinstance(input_str, list) and isinstance(items, (str, type(None))):
            items, input_str = input_str, items

        items = items or []
        val = (str(input_str) if input_str is not None else "").strip()
        if not val:
            if items:
                return items[0]
            raise ResourceNotFoundError(val, items, resource_type)

        if title_key and not title_fn:
            _title = lambda it: str(it.get(title_key, ''))
        else:
            _title = title_fn or cls.get_resource_title

        if id_key and not id_fn:
            _id = lambda it: str(it.get(id_key, ''))
        else:
            _id = id_fn or cls.get_resource_id

        # 1. NUMBER PRIORITY
        if val.isdigit():
            num = int(val)
            if 1 <= num <= len(items):
                return items[num - 1]
            if offset > 0 and 1 <= (num - offset) <= len(items):
                return items[num - offset - 1]
            for it in items:
                if _id(it) == val:
                    return it
            raise ResourceNotFoundError(val, items, resource_type)

        # 2. ALIAS PRIORITY
        clean_alias = val.strip().lower()
        alias_target_id = None
        # Check config_manager
        if config_manager and module:
            aliases = config_manager.get(f'{module}.aliases', {}) or {}
            if isinstance(aliases, dict) and clean_alias in aliases:
                alias_target_id = aliases[clean_alias]
        # Check in-memory aliases
        if not alias_target_id:
            mod_key = (module or resource_type).lower()
            if mod_key in cls._aliases and clean_alias in cls._aliases[mod_key]:
                alias_target_id = cls._aliases[mod_key][clean_alias]

        if alias_target_id:
            for it in items:
                if _id(it) == alias_target_id or _title(it).lower() == alias_target_id.lower():
                    return it
            if fetch_fn:
                try:
                    fetched = fetch_fn(alias_target_id)
                    if fetched:
                        return fetched
                except Exception:
                    pass
            raise AliasDeletedError(clean_alias, items, resource_type)

        # 3. EXACT NAME / TITLE MATCH (case-insensitive)
        val_lower = val.lower()
        exact_matches = [
            it for it in items
            if _title(it).strip().lower() == val_lower
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]
        elif len(exact_matches) > 1:
            if not allow_prompt:
                raise AmbiguousResourceNameError(val, exact_matches, resource_type)
            print()
            print(Fore.YELLOW + f"Multiple {resource_type.lower()}s found matching '{val}':")
            return cls.prompt_selection(exact_matches, resource_name=resource_type, title_fn=_title, id_fn=_id)

        # 4. SUBSTRING / SEARCH MATCH (case-insensitive)
        sub_matches = [
            it for it in items
            if val_lower in _title(it).lower()
        ]
        if len(sub_matches) == 1:
            return sub_matches[0]
        elif len(sub_matches) > 1:
            if not allow_prompt:
                raise AmbiguousResourceNameError(val, sub_matches, resource_type)
            print()
            print(Fore.YELLOW + f"Multiple {resource_type.lower()}s found matching '{val}':")
            return cls.prompt_selection(sub_matches, resource_name=resource_type, title_fn=_title, id_fn=_id)

        # 5. DIRECT RESOURCE ID MATCH
        for it in items:
            if _id(it) == val:
                return it

        # If direct ID passed and fetch_fn is provided, query API directly
        if fetch_fn:
            try:
                fetched = fetch_fn(val)
                if fetched:
                    return fetched
            except Exception:
                pass

        raise ResourceNotFoundError(val, items, resource_type)

    # -----------------------------------------------------------------------
    # Alias Management
    # -----------------------------------------------------------------------
    @classmethod
    def set_alias(
        cls,
        module: str,
        alias_name_or_ref: str,
        target_id_or_alias: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
        config_manager: Optional[Any] = None,
        resource_type: str = "Resource",
        fetch_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None
    ) -> Any:
        """Create or update a friendly alias for any module resource."""
        mod_key = module.lower()
        if mod_key not in cls._aliases:
            cls._aliases[mod_key] = {}

        # 3-arg direct style: set_alias(module, alias_name, target_id)
        if items is None and config_manager is None:
            clean_alias = alias_name_or_ref.strip().lower()
            cls._aliases[mod_key][clean_alias] = target_id_or_alias or ""
            return True, f"{clean_alias} → {target_id_or_alias}"

        # 5/6-arg interactive/config style
        target_reference = alias_name_or_ref
        alias_name = target_id_or_alias or ""
        clean_alias = alias_name.strip().lower()
        if not clean_alias:
            return False, "Alias name cannot be empty."
        if clean_alias.isdigit():
            return False, "Alias name cannot be a pure number."

        try:
            resolved_item = cls.resolve(
                target_reference, items or [], module=module,
                resource_type=resource_type, config_manager=config_manager,
                fetch_fn=fetch_fn
            )
        except ResourceNotFoundError:
            return False, f"{resource_type} not found: '{target_reference}'."
        except AmbiguousResourceNameError:
            return False, f"Multiple {resource_type.lower()}s match '{target_reference}'. Please specify by number or exact ID."
        except Exception as e:
            return False, f"Error resolving target: {e}"

        target_id = cls.get_resource_id(resolved_item)
        target_name = cls.get_resource_title(resolved_item)

        cls._aliases[mod_key][clean_alias] = target_id

        if config_manager:
            key = f'{module}.aliases'
            aliases = config_manager.get(key, {}) or {}
            if not isinstance(aliases, dict):
                aliases = {}
            aliases[clean_alias] = target_id
            config_manager.set(key, aliases)
            if config_manager.save_config():
                return True, f"{clean_alias} → {target_name}"
            return False, "Failed to save configuration."
        return True, f"{clean_alias} → {target_name}"

    @classmethod
    def get_aliases(cls, module: str, config_manager: Optional[Any] = None) -> Any:
        """Retrieve aliases for a given module."""
        mod_key = module.lower()
        res = dict(cls._aliases.get(mod_key, {}))
        if config_manager:
            cfg_aliases = config_manager.get(f'{module}.aliases', {}) or {}
            if isinstance(cfg_aliases, dict):
                res.update(cfg_aliases)
        return res

    @classmethod
    def resolve_alias(cls, module: str, alias_name: str, config_manager: Optional[Any] = None) -> Optional[str]:
        """Resolve alias name to target ID."""
        aliases = cls.get_aliases(module, config_manager)
        return aliases.get(alias_name.strip().lower())

    @classmethod
    def remove_alias(cls, module: str, alias_name: str, config_manager: Optional[Any] = None) -> bool:
        """Remove a resource alias."""
        clean = alias_name.strip().lower()
        removed = False
        mod_key = module.lower()
        if mod_key in cls._aliases and clean in cls._aliases[mod_key]:
            del cls._aliases[mod_key][clean]
            removed = True
        if config_manager:
            key = f'{module}.aliases'
            aliases = config_manager.get(key, {}) or {}
            if isinstance(aliases, dict) and clean in aliases:
                del aliases[clean]
                config_manager.set(key, aliases)
                config_manager.save_config()
                removed = True
        return removed

    # -----------------------------------------------------------------------
    # Numbered List Formatting
    # -----------------------------------------------------------------------
    @classmethod
    def format_resource_list(
        cls,
        items: List[Dict[str, Any]],
        title_fn: Optional[Callable[[Dict[str, Any]], str]] = None,
        subtitle_fn: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        start_index: int = 1
    ) -> str:
        """
        Display a clean numbered list according to Hermes CLI style:
        [1] Resource Title
            Resource Subtitle/Metadata
        Never prints long raw IDs!
        """
        lines = []
        _title = title_fn or cls.get_resource_title
        for idx, item in enumerate(items, start_index):
            title = _title(item) or 'Untitled'
            sub = subtitle_fn(item) if subtitle_fn else None
            if sub:
                lines.append(f"[{idx}] {title}\n    {sub}")
            else:
                lines.append(f"[{idx}] {title}")
        return "\n\n".join(lines)

    # -----------------------------------------------------------------------
    # Interactive Selection & Pagination with Inline Retry
    # -----------------------------------------------------------------------
    @classmethod
    def prompt_selection(
        cls,
        items: List[Dict[str, Any]],
        resource_name: str = "Resource",
        module: Optional[str] = None,
        config_manager: Optional[Any] = None,
        title_fn: Optional[Callable[[Dict[str, Any]], str]] = None,
        subtitle_fn: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        id_fn: Optional[Callable[[Dict[str, Any]], str]] = None,
        title_key: Optional[str] = None,
        id_key: Optional[str] = None,
        page_size: int = 5,
        default_index: int = 1,
        allow_search: bool = True,
        search_fn: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
        fetch_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Interactive resource selector with pagination, search, number selection,
        and inline validation retry without terminating on invalid input.
        Returns selected resource dict or None if cancelled/backed out.
        """
        if not items and not search_fn:
            print()
            print(Fore.YELLOW + f"No {resource_name.lower()}s found.\n")
            return None

        if title_key and not title_fn:
            title_fn = lambda it: str(it.get(title_key, ''))
        if id_key and not id_fn:
            id_fn = lambda it: str(it.get(id_key, ''))

        current_items = list(items)
        page = 0
        search_query = ""

        while True:
            clear_screen()
            total_items = len(current_items)
            total_pages = max(1, (total_items + page_size - 1) // page_size) if total_items > 0 else 1
            if page >= total_pages:
                page = max(0, total_pages - 1)

            start_idx = page * page_size
            end_idx = min(start_idx + page_size, total_items)
            page_slice = current_items[start_idx:end_idx]

            print()
            print(Fore.WHITE + Style.BRIGHT + f"Select {resource_name}:")
            print()

            if page_slice:
                formatted_list = cls.format_resource_list(
                    page_slice, title_fn=title_fn, subtitle_fn=subtitle_fn, start_index=start_idx + 1
                )
                print(formatted_list)
                print()
            else:
                print(Fore.YELLOW + f"No {resource_name.lower()}s found matching search.\n")

            # Show navigation options
            nav_hints = []
            if total_pages > 1:
                if page < total_pages - 1:
                    nav_hints.append("[n] Next page")
                if page > 0:
                    nav_hints.append("[p] Previous page")
            if allow_search:
                nav_hints.append("[s] Search")
            nav_hints.append("[b] Back")
            print(Fore.CYAN + "  ".join(nav_hints))
            print()

            # Prompt
            default_str = f" [{default_index}]" if (1 <= default_index <= len(page_slice)) else ""
            prompt_str = f"{resource_name}{default_str}"

            while True:
                try:
                    import click
                    user_input = click.prompt(prompt_str, default="", show_default=False).strip()
                except Exception:
                    print(Fore.CYAN + f"{prompt_str}: ", end="")
                    user_input = input().strip()

                # Handle default enter
                if not user_input and default_str:
                    return page_slice[default_index - 1]

                # Navigation
                if user_input.lower() == 'b':
                    return None
                elif user_input.lower() == 'n' and page < total_pages - 1:
                    page += 1
                    break
                elif user_input.lower() == 'p' and page > 0:
                    page -= 1
                    break
                elif user_input.lower() == 's' and allow_search:
                    try:
                        import click
                        search_query = click.prompt(f"Search {resource_name.lower()}", default="", show_default=False).strip()
                    except Exception:
                        print(Fore.CYAN + f"Search {resource_name.lower()}: ", end="")
                        search_query = input().strip()
                    if search_query:
                        if search_fn:
                            try:
                                current_items = search_fn(search_query)
                            except Exception as e:
                                print_error(f"Search failed: {e}")
                        else:
                            _title = title_fn or cls.get_resource_title
                            current_items = [
                                it for it in items
                                if search_query.lower() in _title(it).lower()
                            ]
                        page = 0
                    else:
                        current_items = list(items)
                        page = 0
                    break

                # Resolve reference
                try:
                    # First attempt resolving against the currently displayed page slice
                    try:
                        resolved = cls.resolve(
                            user_input, page_slice, module=module, resource_type=resource_name,
                            config_manager=config_manager, fetch_fn=fetch_fn,
                            title_fn=title_fn, id_fn=id_fn, offset=start_idx
                        )
                        return resolved
                    except ResourceNotFoundError:
                        # Next attempt resolving against all items
                        resolved = cls.resolve(
                            user_input, current_items, module=module, resource_type=resource_name,
                            config_manager=config_manager, fetch_fn=fetch_fn,
                            title_fn=title_fn, id_fn=id_fn
                        )
                        return resolved

                except AmbiguousResourceNameError as err:
                    print()
                    print(Fore.YELLOW + f"Multiple {resource_name.lower()}s found:\n")
                    for m_idx, m_it in enumerate(err.matching_resources, 1):
                        _title = title_fn or cls.get_resource_title
                        print(f"[{m_idx}] {_title(m_it)}")
                    print()
                    try:
                        import click
                        disambig_input = click.prompt("Select by number [1]", default="1", show_default=False).strip() or "1"
                    except Exception:
                        print(Fore.CYAN + f"Select by number [1]: ", end="")
                        disambig_input = input().strip() or "1"
                    try:
                        if disambig_input.isdigit() and 1 <= int(disambig_input) <= len(err.matching_resources):
                            return err.matching_resources[int(disambig_input) - 1]
                    except Exception:
                        pass
                    print_error(f"{resource_name} not found.")
                    continue

                except AliasDeletedError as err:
                    print()
                    print_error(f"Alias '{err.alias}' points to a {resource_name.lower()} that is no longer available.")
                    continue

                except ResourceNotFoundError:
                    print()
                    print_error(f"{resource_name} not found.")
                    continue

                except ResourceResolutionError as err:
                    print()
                    print_error(str(err))
                    continue

    # -----------------------------------------------------------------------
    # Universal Action Flows: Confirm, Delete, Update, Info
    # -----------------------------------------------------------------------
    @staticmethod
    def confirm_action(prompt_text: str, default: bool = False, default_yes: Optional[bool] = None) -> bool:
        """
        Safe confirmation prompt for actions.
        default=False -> [y/N] (destructive, defaults to No)
        default=True  -> [Y/n] (update, defaults to Yes)
        """
        if default_yes is not None:
            default = default_yes
        hint = "[Y/n]" if default else "[y/N]"
        full_prompt = f"{prompt_text} {hint}"
        try:
            import click
            choice = click.prompt(full_prompt, default="y" if default else "n", show_default=False).strip().lower()
        except Exception:
            print(Fore.CYAN + f"{full_prompt}: ", end="")
            choice = input().strip().lower()
        if not choice:
            return default
        return choice in ('y', 'yes')

    @classmethod
    def execute_delete_flow(
        cls,
        resource: Optional[Dict[str, Any]] = None,
        display_details_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
        delete_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
        resource_name: str = "Resource",
        details: Optional[Dict[str, Any]] = None,
        item: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Universal Delete Flow:
        SELECT -> VIEW -> CONFIRM -> DELETE
        Never deletes without explicit confirmation.
        """
        target = resource or item
        if not target:
            return False
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + f"{resource_name} Details")
        print(Fore.WHITE + "=" * 60)
        print()
        if display_details_fn:
            display_details_fn(target)
        elif details:
            print_key_value_pairs(details)
        print()
        if not cls.confirm_action(f"Delete this {resource_name.lower()}?", default_yes=False):
            print()
            print_info("Operation cancelled.")
            return False

        print()
        success = delete_fn(target) if delete_fn else False
        if success:
            print_success(f"{resource_name} deleted successfully.")
            return True
        else:
            print_error(f"Failed to delete {resource_name.lower()}.")
            return False

    @classmethod
    def execute_update_flow(
        cls,
        resource: Optional[Dict[str, Any]] = None,
        display_details_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
        fields: Optional[List[Dict[str, Any]]] = None,
        update_fn: Optional[Callable[[Dict[str, Any], Dict[str, Any]], bool]] = None,
        resource_name: str = "Resource",
        details: Optional[Dict[str, Any]] = None,
        item: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Universal Update Flow:
        SELECT -> VIEW CURRENT DATA -> CHOOSE WHAT TO EDIT -> ENTER NEW VALUE ->
        VALIDATE -> SHOW CHANGES -> CONFIRM -> UPDATE
        """
        target = resource or item
        if not target or not fields:
            return False
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + f"{resource_name} Details")
        print(Fore.WHITE + "=" * 60)
        print()
        if display_details_fn:
            display_details_fn(target)
        elif details:
            print_key_value_pairs(details)
        print()

        print(Fore.WHITE + Style.BRIGHT + "What do you want to edit?")
        print()
        for idx, fld in enumerate(fields, 1):
            print(f"[{idx}] {fld['label']}")
        print("[b] Back")
        print()
        try:
            import click
            f_choice = click.prompt("Select [1]", default="1", show_default=False).strip()
        except Exception:
            print(Fore.CYAN + "Select [1]: ", end="")
            f_choice = input().strip()
        if f_choice.lower() == 'b':
            return False
        f_idx = int(f_choice) - 1 if f_choice.isdigit() else 0
        if not (0 <= f_idx < len(fields)):
            print_error("Invalid selection.")
            return False

        selected_field = fields[f_idx]
        field_key = selected_field.get('key') or selected_field.get('name')
        field_label = selected_field['label']
        validator = selected_field.get('validator')
        current_val = selected_field.get('current', target.get(field_key, ''))

        # Prompt for new value with inline retry
        new_val = None
        while True:
            try:
                import click
                raw_input = click.prompt(f"Enter new {field_label}", default="", show_default=False).strip()
            except Exception:
                print(Fore.CYAN + f"Enter new {field_label}: ", end="")
                raw_input = input().strip()
            if validator:
                is_valid, validated_val, err_msg = validator(raw_input)
                if not is_valid:
                    print()
                    print_error(err_msg or f"Invalid {field_label}.")
                    continue
                new_val = validated_val
                break
            else:
                new_val = raw_input
                break

        # Show changes summary
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + "Review Changes:")
        print(Fore.WHITE + "=" * 60)
        print(Fore.YELLOW + f"{field_label}:")
        print(Fore.RED + f"  - Current : {current_val}")
        print(Fore.GREEN + f"  + New     : {new_val}")
        print()

        if not cls.confirm_action("Apply these changes?", default_yes=True):
            print()
            print_info("Update cancelled.")
            return False

        print()
        success = update_fn(target, {field_key: new_val}) if update_fn else False
        if success:
            print_success(f"{resource_name} updated successfully.")
            return True
        else:
            print_error(f"Failed to update {resource_name.lower()}.")
            return False
