"""
CLI command implementations for Personal Profile (hermes profile ...).
"""

import click
from pathlib import Path
from colorama import Fore, Style
from tabulate import tabulate

from .service import PersonalProfileService
from .resolver import ProfileResolver
from ..utils.formatters import print_success, print_error, print_info, print_warning, print_header


@click.group('profile')
def profile_group():
    """Manage your reusable personal information and profile settings"""
    pass


@profile_group.command('show')
@click.pass_context
def profile_show(ctx):
    """Display your profile overview (masks sensitive data)"""
    config_manager = ctx.obj.get('config_manager') if ctx.obj else None
    from .storage import PersonalProfileRepository
    repo = PersonalProfileRepository(config_manager=config_manager)
    service = PersonalProfileService(repository=repo)
    resolver = ProfileResolver(service=service)
    p = service.get_profile()

    print_header("👤 Personal Profile Overview")
    
    table_data = [
        ["Full Name", resolver.get("name") or "(not set)"],
        ["Display Name", p.basic.displayName or "(not set)"],
        ["Primary Email", resolver.get("email") or "(not set)"],
        ["Phone", "******** (sensitive)" if resolver.get("phone") else "(not set)"],
        ["Job Title", resolver.get("job_title") or "(not set)"],
        ["Company", resolver.get("company") or "(not set)"],
        ["College / University", resolver.get("college") or "(not set)"],
        ["Degree", resolver.get("degree") or "(not set)"],
        ["GitHub", resolver.get("github") or "(not set)"],
        ["LinkedIn", resolver.get("linkedin") or "(not set)"],
        ["Portfolio", resolver.get("portfolio") or "(not set)"],
        ["Addresses Configured", str(len(p.addresses))],
        ["Education Records", str(len(p.education))],
        ["Custom Fields", str(len(p.custom_fields))],
        ["Snippets", str(len(p.snippets))],
        ["Profile Lock", "Locked" if p.privacy.is_locked else "Unlocked"],
    ]

    print(tabulate(table_data, headers=["Field", "Value"], tablefmt="simple"))


@profile_group.command('get')
@click.argument('field_name')
@click.pass_context
def profile_get(ctx, field_name):
    """Retrieve the value of a specific profile field or alias"""
    config_manager = ctx.obj.get('config_manager') if ctx.obj else None
    from .storage import PersonalProfileRepository
    repo = PersonalProfileRepository(config_manager=config_manager)
    service = PersonalProfileService(repository=repo)
    resolver = ProfileResolver(service=service)

    val = resolver.get(field_name)
    if val:
        print(f"{Fore.GREEN}{val}{Style.RESET_ALL}")
    else:
        print_info(f"Field '{field_name}' is not configured.")


@profile_group.command('set')
@click.argument('field_name')
@click.argument('value')
@click.pass_context
def profile_set(ctx, field_name, value):
    """Set the value of a profile field"""
    config_manager = ctx.obj.get('config_manager') if ctx.obj else None
    from .storage import PersonalProfileRepository
    repo = PersonalProfileRepository(config_manager=config_manager)
    service = PersonalProfileService(repository=repo)
    
    # Map to section
    fn = field_name.strip().lower()
    basic_keys = {'fullname': 'fullName', 'firstname': 'firstName', 'lastname': 'lastName', 'displayname': 'displayName', 'dob': 'dateOfBirth', 'dateofbirth': 'dateOfBirth'}
    contact_keys = {'email': 'primaryEmail', 'primaryemail': 'primaryEmail', 'personalemail': 'personalEmail', 'workemail': 'workEmail', 'phone': 'phone', 'alternatephone': 'alternatePhone'}
    prof_keys = {'jobtitle': 'jobTitle', 'job_title': 'jobTitle', 'company': 'company', 'department': 'department', 'experience': 'experience', 'github': 'github', 'linkedin': 'linkedin', 'portfolio': 'portfolio', 'website': 'website'}

    success = False
    clean_val = value.strip()

    if fn in basic_keys:
        success = service.update_basic_field(basic_keys[fn], clean_val)
    elif fn in contact_keys:
        success = service.update_contact_field(contact_keys[fn], clean_val)
    elif fn in prof_keys:
        success = service.update_professional_field(prof_keys[fn], clean_val)
    elif fn == 'skills':
        success = service.update_professional_field('skills', clean_val)
    else:
        # Save as custom field
        service.add_custom_field(field_name, field_name.replace('_', ' ').capitalize(), clean_val)
        success = True

    if success:
        print_success(f"Profile field '{field_name}' updated successfully.")
    else:
        print_error(f"Failed to update profile field '{field_name}'. (Profile may be locked)")


@profile_group.command('resolve')
@click.argument('template_text')
@click.pass_context
def profile_resolve(ctx, template_text):
    """Resolve a text string containing profile variables (e.g. {{name}})"""
    config_manager = ctx.obj.get('config_manager') if ctx.obj else None
    from .storage import PersonalProfileRepository
    repo = PersonalProfileRepository(config_manager=config_manager)
    service = PersonalProfileService(repository=repo)
    resolver = ProfileResolver(service=service)

    resolved = resolver.resolveTemplate(template_text)
    print(resolved)


@profile_group.command('export')
@click.option('--file', 'file_path', help='Output JSON file path')
@click.pass_context
def profile_export(ctx, file_path):
    """Export profile data to a JSON file"""
    config_manager = ctx.obj.get('config_manager') if ctx.obj else None
    from .storage import PersonalProfileRepository
    repo = PersonalProfileRepository(config_manager=config_manager)
    service = PersonalProfileService(repository=repo)

    print_warning("Exporting your personal profile may expose sensitive information.")
    if not click.confirm("Do you want to continue?"):
        print_info("Export cancelled.")
        return

    json_str = service.export_profile_json()
    if file_path:
        out_path = Path(file_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding='utf-8')
        print_success(f"Profile successfully exported to {out_path}")
    else:
        print(json_str)


@profile_group.command('import')
@click.option('--file', 'file_path', required=True, help='Path to profile JSON file')
@click.pass_context
def profile_import(ctx, file_path):
    """Import profile data from a JSON file"""
    path = Path(file_path).resolve()
    if not path.exists():
        print_error(f"File not found: {path}")
        return

    config_manager = ctx.obj.get('config_manager') if ctx.obj else None
    from .storage import PersonalProfileRepository
    repo = PersonalProfileRepository(config_manager=config_manager)
    service = PersonalProfileService(repository=repo)

    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        print_error(f"Failed to read file: {e}")
        return

    ok, preview_or_err, new_profile = service.import_profile_json(content)
    if not ok or not new_profile:
        print_error(f"Import validation failed: {preview_or_err}")
        return

    print_header("Profile Import Preview")
    print(preview_or_err)
    print()
    if click.confirm("Are you sure you want to overwrite your existing profile with this data?"):
        if service.apply_import(new_profile):
            print_success("Profile imported successfully.")
        else:
            print_error("Failed to save imported profile.")
    else:
        print_info("Import cancelled.")
