"""
Interactive terminal UI for Personal Profile in Hermes CLI.
Follows existing Hermes styling, page-transition rules, and validation flows.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from colorama import Fore, Style

from ..profile.service import PersonalProfileService
from ..profile.resolver import ProfileResolver
from ..profile.storage import PersonalProfileRepository
from ..profile.validators import (
    validate_email, validate_phone, validate_url,
    validate_date, validate_postal_code, validate_non_empty, validate_custom_key
)
from ..utils.formatters import print_success, print_error, print_info, print_warning


class PersonalProfileUI:
    """
    Renders Personal Profile menus, submenus, and Gmail Compose integration.
    """

    def __init__(self, menu):
        self.menu = menu
        repo = PersonalProfileRepository(config_manager=getattr(menu, 'config_manager', None))
        self.service = PersonalProfileService(repository=repo)
        self.resolver = ProfileResolver(service=self.service)

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _print_header(self, title: str):
        self.menu.clear_screen()
        width = self.menu.get_width()
        self.menu.draw_box([title], color=Fore.CYAN, padding=10)
        print()

    def _prompt_choice(self, prompt_text: str = "Choose an option: ") -> str:
        width = self.menu.get_width()
        offset = max(0, (width - len(prompt_text)) // 2)
        margin = " " * offset
        print(margin + Fore.CYAN + prompt_text, end="", flush=True)
        return self.menu.get_user_choice()

    def _print_centered_lines(self, lines: List[str], color=Fore.WHITE):
        width = self.menu.get_width()
        max_len = max((len(line) for line in lines), default=30)
        offset = max(0, (width - max_len) // 2)
        margin = " " * offset
        for line in lines:
            print(margin + color + line)

    # ── 1. Main Profile Screen ─────────────────────────────────────────────────

    def show_main_profile_menu(self):
        self._print_header("Personal Profile")
        stats = self.service.get_summary_stats()
        
        lock_str = " (LOCKED)" if stats.get('is_locked') else ""
        lines = [
            f"Manage your reusable personal information{lock_str}",
            "",
            "Profile Status",
            "--------------------------------------------------",
            f"Name        : {stats['name']}",
            f"Email       : {stats['email']}",
            f"Fields      : {stats['fields_count']} configured",
            f"Snippets    : {stats['snippets_count']}",
            f"Auto-use    : {stats['auto_use']}",
            "--------------------------------------------------",
            "",
            "[1] Basic Information",
            "[2] Contact Information",
            "[3] Address Information",
            "[4] Professional Information",
            "[5] Education Information",
            "[6] Online Information",
            "[7] Custom Information",
            "[8] Profile Snippets",
            "[9] Privacy & Security",
            "",
            "[b] Back to Main Menu",
            "[0] Exit",
        ]
        self._print_centered_lines(lines, color=Fore.WHITE + Style.BRIGHT)

    def handle_profile_menu(self):
        while True:
            self.show_main_profile_menu()
            print()
            choice = self._prompt_choice("Choose an option [0-9, b]: ")
            if choice == '0':
                self.menu.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.handle_basic_menu()
            elif choice == '2':
                self.handle_contact_menu()
            elif choice == '3':
                self.handle_address_menu()
            elif choice == '4':
                self.handle_professional_menu()
            elif choice == '5':
                self.handle_education_menu()
            elif choice == '6':
                self.handle_online_menu()
            elif choice == '7':
                self.handle_custom_menu()
            elif choice == '8':
                self.handle_snippets_menu()
            elif choice == '9':
                self.handle_privacy_menu()
            else:
                self.menu.show_error("Invalid choice. Please select 0-9 or b.")

    # ── 2. Basic Information ───────────────────────────────────────────────────

    def handle_basic_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Basic Information")
            lines = [
                f"Full Name       : {p.basic.fullName or 'Not set'}",
                f"First Name      : {p.basic.firstName or 'Not set'}",
                f"Last Name       : {p.basic.lastName or 'Not set'}",
                f"Display Name    : {p.basic.displayName or 'Not set'}",
                f"Date of Birth   : {p.basic.dateOfBirth or 'Not set'}",
                "",
                "[1] Edit Full Name",
                "[2] Edit First Name",
                "[3] Edit Last Name",
                "[4] Edit Display Name",
                "[5] Edit Date of Birth",
                "[6] Clear Field",
                "",
                "[b] Back",
            ]
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-6, b]: ")
            if choice == 'b':
                break

            fields_map = {
                '1': ('fullName', 'Full Name', validate_non_empty),
                '2': ('firstName', 'First Name', validate_non_empty),
                '3': ('lastName', 'Last Name', validate_non_empty),
                '4': ('displayName', 'Display Name', validate_non_empty),
                '5': ('dateOfBirth', 'Date of Birth (YYYY-MM-DD)', validate_date),
            }

            if choice in fields_map:
                field_attr, label, validator = fields_map[choice]
                self._edit_single_field(
                    label=label,
                    current_val=getattr(p.basic, field_attr),
                    validator=validator,
                    save_fn=lambda val: self.service.update_basic_field(field_attr, val)
                )
            elif choice == '6':
                self._clear_menu([
                    ('1', 'Full Name', lambda: self.service.clear_basic_field('fullName')),
                    ('2', 'First Name', lambda: self.service.clear_basic_field('firstName')),
                    ('3', 'Last Name', lambda: self.service.clear_basic_field('lastName')),
                    ('4', 'Display Name', lambda: self.service.clear_basic_field('displayName')),
                    ('5', 'Date of Birth', lambda: self.service.clear_basic_field('dateOfBirth')),
                ])
            else:
                self.menu.show_error("Invalid choice.")

    # ── 3. Contact Information ─────────────────────────────────────────────────

    def handle_contact_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Contact Information")
            lines = [
                f"Primary Email   : {p.contact.primaryEmail or 'Not set'}",
                f"Personal Email  : {p.contact.personalEmail or 'Not set'}",
                f"Work Email      : {p.contact.workEmail or 'Not set'}",
                f"Phone           : {p.contact.phone or 'Not set'}",
                f"Alternate Phone : {p.contact.alternatePhone or 'Not set'}",
                "",
                "[1] Edit Primary Email",
                "[2] Edit Personal Email",
                "[3] Edit Work Email",
                "[4] Edit Phone",
                "[5] Edit Alternate Phone",
                "[6] Clear Field",
                "",
                "[b] Back",
            ]
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-6, b]: ")
            if choice == 'b':
                break

            fields_map = {
                '1': ('primaryEmail', 'Primary Email', validate_email),
                '2': ('personalEmail', 'Personal Email', validate_email),
                '3': ('workEmail', 'Work Email', validate_email),
                '4': ('phone', 'Phone Number', validate_phone),
                '5': ('alternatePhone', 'Alternate Phone Number', validate_phone),
            }

            if choice in fields_map:
                field_attr, label, validator = fields_map[choice]
                self._edit_single_field(
                    label=label,
                    current_val=getattr(p.contact, field_attr),
                    validator=validator,
                    save_fn=lambda val: self.service.update_contact_field(field_attr, val)
                )
            elif choice == '6':
                self._clear_menu([
                    ('1', 'Primary Email', lambda: self.service.clear_contact_field('primaryEmail')),
                    ('2', 'Personal Email', lambda: self.service.clear_contact_field('personalEmail')),
                    ('3', 'Work Email', lambda: self.service.clear_contact_field('workEmail')),
                    ('4', 'Phone', lambda: self.service.clear_contact_field('phone')),
                    ('5', 'Alternate Phone', lambda: self.service.clear_contact_field('alternatePhone')),
                ])
            else:
                self.menu.show_error("Invalid choice.")

    # ── 4. Address Information ─────────────────────────────────────────────────

    def handle_address_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Address Information")
            lines = ["Configured Addresses:"]
            if not p.addresses:
                lines.append("  (No addresses configured)")
            else:
                for idx, addr in enumerate(p.addresses, 1):
                    lines.append(f"  [{idx}] {addr.label}: {addr.to_formatted_string() or 'Empty address'}")
            
            lines.extend([
                "",
                "[1] Add Address",
                "[2] Edit Address",
                "[3] Delete Address",
                "",
                "[b] Back",
            ])
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-3, b]: ")
            if choice == 'b':
                break

            if choice == '1':
                self._add_address_flow()
            elif choice == '2':
                if not p.addresses:
                    self.menu.show_error("No addresses to edit.")
                    continue
                print(Fore.CYAN + f"Select address to edit [1-{len(p.addresses)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.addresses):
                    self._edit_address_flow(int(sel) - 1)
                else:
                    self.menu.show_error("Invalid address selection.")
            elif choice == '3':
                if not p.addresses:
                    self.menu.show_error("No addresses to delete.")
                    continue
                print(Fore.CYAN + f"Select address to delete [1-{len(p.addresses)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.addresses):
                    idx = int(sel) - 1
                    self.service.delete_address(idx)
                    print_success("Address deleted successfully.")
                else:
                    self.menu.show_error("Invalid address selection.")
            else:
                self.menu.show_error("Invalid choice.")

    def _add_address_flow(self):
        print(Fore.CYAN + "\nLabel (Home/College/Work/Other) [Home]: ", end="")
        label = input().strip() or "Home"
        print(Fore.CYAN + "Street: ", end="")
        street = input().strip()
        print(Fore.CYAN + "City: ", end="")
        city = input().strip()
        print(Fore.CYAN + "State: ", end="")
        state = input().strip()
        print(Fore.CYAN + "Country: ", end="")
        country = input().strip()

        while True:
            print(Fore.CYAN + "Postal Code: ", end="")
            postal = input().strip()
            if not postal:
                break
            ok, err = validate_postal_code(postal)
            if not ok:
                print(Fore.RED + f"✗ {err}")
                continue
            break

        self.service.add_address(label, street, city, state, country, postal)
        print_success("Address added successfully.")

    def _edit_address_flow(self, idx: int):
        p = self.service.get_profile()
        addr = p.addresses[idx]
        print(Fore.CYAN + f"\nEditing {addr.label} Address (press Enter to keep current value):")
        
        print(Fore.CYAN + f"Label [{addr.label}]: ", end="")
        new_label = input().strip()
        if new_label: addr.label = new_label
        
        print(Fore.CYAN + f"Street [{addr.street}]: ", end="")
        new_street = input().strip()
        if new_street: addr.street = new_street

        print(Fore.CYAN + f"City [{addr.city}]: ", end="")
        new_city = input().strip()
        if new_city: addr.city = new_city

        print(Fore.CYAN + f"State [{addr.state}]: ", end="")
        new_state = input().strip()
        if new_state: addr.state = new_state

        print(Fore.CYAN + f"Country [{addr.country}]: ", end="")
        new_country = input().strip()
        if new_country: addr.country = new_country

        while True:
            print(Fore.CYAN + f"Postal Code [{addr.postalCode}]: ", end="")
            new_postal = input().strip()
            if not new_postal:
                break
            ok, err = validate_postal_code(new_postal)
            if not ok:
                print(Fore.RED + f"✗ {err}")
                continue
            addr.postalCode = new_postal
            break

        self.service.save_profile()
        print_success("Address updated successfully.")

    # ── 5. Professional Information ────────────────────────────────────────────

    def handle_professional_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Professional Information")
            skills_str = ", ".join(p.professional.skills) if p.professional.skills else 'Not set'
            lines = [
                f"Job Title       : {p.professional.jobTitle or 'Not set'}",
                f"Company         : {p.professional.company or 'Not set'}",
                f"Department      : {p.professional.department or 'Not set'}",
                f"Experience      : {p.professional.experience or 'Not set'}",
                f"Skills          : {skills_str}",
                f"GitHub          : {p.professional.github or 'Not set'}",
                f"LinkedIn        : {p.professional.linkedin or 'Not set'}",
                f"Portfolio       : {p.professional.portfolio or 'Not set'}",
                f"Website         : {p.professional.website or 'Not set'}",
                "",
                "[1] Edit Job Title",
                "[2] Edit Company",
                "[3] Edit Department",
                "[4] Edit Experience",
                "[5] Edit Skills (comma-separated)",
                "[6] Edit GitHub",
                "[7] Edit LinkedIn",
                "[8] Edit Portfolio",
                "[9] Edit Website",
                "[10] Clear Field",
                "",
                "[b] Back",
            ]
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-10, b]: ")
            if choice == 'b':
                break

            fields_map = {
                '1': ('jobTitle', 'Job Title', validate_non_empty),
                '2': ('company', 'Company', validate_non_empty),
                '3': ('department', 'Department', validate_non_empty),
                '4': ('experience', 'Experience', validate_non_empty),
                '5': ('skills', 'Skills (comma-separated)', validate_non_empty),
                '6': ('github', 'GitHub URL', validate_url),
                '7': ('linkedin', 'LinkedIn URL', validate_url),
                '8': ('portfolio', 'Portfolio URL', validate_url),
                '9': ('website', 'Website URL', validate_url),
            }

            if choice in fields_map:
                field_attr, label, validator = fields_map[choice]
                current_val = getattr(p.professional, field_attr)
                if isinstance(current_val, list):
                    current_val = ", ".join(current_val)
                self._edit_single_field(
                    label=label,
                    current_val=current_val,
                    validator=validator,
                    save_fn=lambda val: self.service.update_professional_field(field_attr, val)
                )
            elif choice == '10':
                self._clear_menu([
                    ('1', 'Job Title', lambda: self.service.clear_professional_field('jobTitle')),
                    ('2', 'Company', lambda: self.service.clear_professional_field('company')),
                    ('3', 'Department', lambda: self.service.clear_professional_field('department')),
                    ('4', 'Experience', lambda: self.service.clear_professional_field('experience')),
                    ('5', 'Skills', lambda: self.service.clear_professional_field('skills')),
                    ('6', 'GitHub', lambda: self.service.clear_professional_field('github')),
                    ('7', 'LinkedIn', lambda: self.service.clear_professional_field('linkedin')),
                    ('8', 'Portfolio', lambda: self.service.clear_professional_field('portfolio')),
                    ('9', 'Website', lambda: self.service.clear_professional_field('website')),
                ])
            else:
                self.menu.show_error("Invalid choice.")

    # ── 6. Education Information ───────────────────────────────────────────────

    def handle_education_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Education Information")
            lines = ["Configured Education Records:"]
            if not p.education:
                lines.append("  (No education records configured)")
            else:
                for idx, edu in enumerate(p.education, 1):
                    dept = f", {edu.department}" if edu.department else ""
                    yr = f" ({edu.year})" if edu.year else ""
                    sid = f" [ID: {edu.studentId}]" if edu.studentId else ""
                    lines.append(f"  [{idx}] {edu.institution or 'Unknown Institution'} - {edu.degree or 'Degree'}{dept}{yr}{sid}")

            lines.extend([
                "",
                "[1] Add Education Record",
                "[2] Edit Education Record",
                "[3] Delete Education Record",
                "",
                "[b] Back",
            ])
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-3, b]: ")
            if choice == 'b':
                break

            if choice == '1':
                self._add_education_flow()
            elif choice == '2':
                if not p.education:
                    self.menu.show_error("No education records to edit.")
                    continue
                print(Fore.CYAN + f"Select record to edit [1-{len(p.education)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.education):
                    self._edit_education_flow(int(sel) - 1)
                else:
                    self.menu.show_error("Invalid record selection.")
            elif choice == '3':
                if not p.education:
                    self.menu.show_error("No education records to delete.")
                    continue
                print(Fore.CYAN + f"Select record to delete [1-{len(p.education)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.education):
                    self.service.delete_education(int(sel) - 1)
                    print_success("Education record deleted successfully.")
                else:
                    self.menu.show_error("Invalid selection.")
            else:
                self.menu.show_error("Invalid choice.")

    def _add_education_flow(self):
        print(Fore.CYAN + "\nInstitution / College: ", end="")
        inst = input().strip()
        print(Fore.CYAN + "Degree / Program: ", end="")
        deg = input().strip()
        print(Fore.CYAN + "Department (optional): ", end="")
        dept = input().strip()
        print(Fore.CYAN + "University (optional): ", end="")
        univ = input().strip()
        print(Fore.CYAN + "Year of Completion (optional): ", end="")
        year = input().strip()
        print(Fore.CYAN + "Student ID (sensitive, optional): ", end="")
        sid = input().strip()

        self.service.add_education(inst, deg, dept, univ, year, sid)
        print_success("Education record added successfully.")

    def _edit_education_flow(self, idx: int):
        p = self.service.get_profile()
        edu = p.education[idx]
        print(Fore.CYAN + f"\nEditing Education Record (press Enter to keep current):")
        print(Fore.CYAN + f"Institution [{edu.institution}]: ", end="")
        n_inst = input().strip()
        if n_inst: edu.institution = n_inst

        print(Fore.CYAN + f"Degree [{edu.degree}]: ", end="")
        n_deg = input().strip()
        if n_deg: edu.degree = n_deg

        print(Fore.CYAN + f"Department [{edu.department}]: ", end="")
        n_dept = input().strip()
        if n_dept: edu.department = n_dept

        print(Fore.CYAN + f"University [{edu.university}]: ", end="")
        n_univ = input().strip()
        if n_univ: edu.university = n_univ

        print(Fore.CYAN + f"Year [{edu.year}]: ", end="")
        n_yr = input().strip()
        if n_yr: edu.year = n_yr

        print(Fore.CYAN + f"Student ID [{edu.studentId}]: ", end="")
        n_sid = input().strip()
        if n_sid: edu.studentId = n_sid

        self.service.save_profile()
        print_success("Education record updated successfully.")

    # ── 7. Online Information ──────────────────────────────────────────────────

    def handle_online_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Online Information")
            lines = [
                f"GitHub          : {p.professional.github or 'Not set'}",
                f"LinkedIn        : {p.professional.linkedin or 'Not set'}",
                f"Portfolio       : {p.professional.portfolio or 'Not set'}",
                f"Website         : {p.professional.website or 'Not set'}",
                "",
                "[1] Edit GitHub",
                "[2] Edit LinkedIn",
                "[3] Edit Portfolio",
                "[4] Edit Website",
                "[5] Clear Field",
                "",
                "[b] Back",
            ]
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-5, b]: ")
            if choice == 'b':
                break

            fields_map = {
                '1': ('github', 'GitHub URL', validate_url),
                '2': ('linkedin', 'LinkedIn URL', validate_url),
                '3': ('portfolio', 'Portfolio URL', validate_url),
                '4': ('website', 'Website URL', validate_url),
            }

            if choice in fields_map:
                field_attr, label, validator = fields_map[choice]
                self._edit_single_field(
                    label=label,
                    current_val=getattr(p.professional, field_attr),
                    validator=validator,
                    save_fn=lambda val: self.service.update_professional_field(field_attr, val)
                )
            elif choice == '5':
                self._clear_menu([
                    ('1', 'GitHub', lambda: self.service.clear_professional_field('github')),
                    ('2', 'LinkedIn', lambda: self.service.clear_professional_field('linkedin')),
                    ('3', 'Portfolio', lambda: self.service.clear_professional_field('portfolio')),
                    ('4', 'Website', lambda: self.service.clear_professional_field('website')),
                ])
            else:
                self.menu.show_error("Invalid choice.")

    # ── 8. Custom Information ──────────────────────────────────────────────────

    def handle_custom_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Custom Information")
            lines = ["Configured Custom Fields:"]
            if not p.custom_fields:
                lines.append("  (No custom fields defined)")
            else:
                for idx, cf in enumerate(p.custom_fields, 1):
                    sens = " [Sensitive]" if cf.sensitivity else ""
                    auto = " [Auto-use: On]" if cf.autoUse else " [Auto-use: Off]"
                    lines.append(f"  [{idx}] {cf.displayName} ({cf.key}): {cf.value}{sens}{auto}")

            lines.extend([
                "",
                "[1] Add Custom Field",
                "[2] Edit Custom Field",
                "[3] Delete Custom Field",
                "",
                "[b] Back",
            ])
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-3, b]: ")
            if choice == 'b':
                break

            if choice == '1':
                self._add_custom_field_flow()
            elif choice == '2':
                if not p.custom_fields:
                    self.menu.show_error("No custom fields to edit.")
                    continue
                print(Fore.CYAN + f"Select custom field to edit [1-{len(p.custom_fields)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.custom_fields):
                    self._edit_custom_field_flow(int(sel) - 1)
                else:
                    self.menu.show_error("Invalid selection.")
            elif choice == '3':
                if not p.custom_fields:
                    self.menu.show_error("No custom fields to delete.")
                    continue
                print(Fore.CYAN + f"Select custom field to delete [1-{len(p.custom_fields)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.custom_fields):
                    self.service.delete_custom_field(int(sel) - 1)
                    print_success("Custom field deleted successfully.")
                else:
                    self.menu.show_error("Invalid selection.")
            else:
                self.menu.show_error("Invalid choice.")

    def _add_custom_field_flow(self):
        while True:
            print(Fore.CYAN + "\nField Name (e.g. Emergency Contact, Preferred Name): ", end="")
            name = input().strip()
            ok, err = validate_custom_key(name)
            if not ok:
                print(Fore.RED + f"✗ {err}")
                continue
            break

        print(Fore.CYAN + "Field Value: ", end="")
        val = input().strip()

        print(Fore.CYAN + "Is this field sensitive? [y/N]: ", end="")
        sens = input().strip().lower() == 'y'

        print(Fore.CYAN + "Allow automatic use in templates/suggestions? [Y/n]: ", end="")
        auto = input().strip().lower() != 'n'

        self.service.add_custom_field(key=name, display_name=name, value=val, sensitivity=sens, auto_use=auto)
        print_success(f"Custom field '{name}' added successfully.")

    def _edit_custom_field_flow(self, idx: int):
        p = self.service.get_profile()
        cf = p.custom_fields[idx]
        print(Fore.CYAN + f"\nEditing Custom Field '{cf.displayName}' (press Enter to keep current):")
        print(Fore.CYAN + f"Value [{cf.value}]: ", end="")
        new_val = input().strip()
        if new_val: cf.value = new_val

        print(Fore.CYAN + f"Is sensitive? (Current: {cf.sensitivity}) [y/n/Enter to keep]: ", end="")
        s_inp = input().strip().lower()
        if s_inp == 'y': cf.sensitivity = True
        elif s_inp == 'n': cf.sensitivity = False

        print(Fore.CYAN + f"Allow auto-use? (Current: {cf.autoUse}) [y/n/Enter to keep]: ", end="")
        a_inp = input().strip().lower()
        if a_inp == 'y': cf.autoUse = True
        elif a_inp == 'n': cf.autoUse = False

        self.service.save_profile()
        print_success("Custom field updated successfully.")

    # ── 9. Profile Snippets ────────────────────────────────────────────────────

    def handle_snippets_menu(self):
        while True:
            self._print_header("Profile Snippets")
            lines = [
                "Reusable templates with profile variables (e.g. {{name}}, {{college}})",
                "",
                "[1] List Snippets",
                "[2] Create Snippet",
                "[3] Edit Snippet",
                "[4] Delete Snippet",
                "[5] Preview Snippet",
                "",
                "[b] Back",
            ]
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-5, b]: ")
            if choice == 'b':
                break

            p = self.service.get_profile()

            if choice == '1':
                # List snippets
                print(Fore.CYAN + Style.BRIGHT + "\nRegistered Snippets:")
                if not p.snippets:
                    print_info("No snippets created yet.")
                else:
                    for i, s in enumerate(p.snippets, 1):
                        print(f"  {Fore.GREEN}[{i}] {s.name}")
                        print(f"      {Style.DIM}{s.content[:60]}...{Style.RESET_ALL}")
                print(Fore.CYAN + "\nPress Enter to return: ", end="")
                input()

            elif choice == '2':
                # Create snippet
                print(Fore.CYAN + "\nSnippet Name: ", end="")
                name = input().strip()
                if not name:
                    self.menu.show_error("Snippet name is required.")
                    continue
                print(Fore.CYAN + "Snippet Content (use variables like {{name}}, {{college}}, {{github}}):")
                print(Fore.WHITE + "Enter content lines (type 'END' on a single line to finish):")
                content_lines = []
                while True:
                    line = input()
                    if line.strip() == 'END':
                        break
                    content_lines.append(line)
                content = "\n".join(content_lines).strip()
                if not content:
                    self.menu.show_error("Snippet content cannot be empty.")
                    continue
                self.service.create_snippet(name, content)
                print_success(f"Snippet '{name}' created successfully.")

            elif choice == '3':
                # Edit snippet
                if not p.snippets:
                    self.menu.show_error("No snippets to edit.")
                    continue
                for i, s in enumerate(p.snippets, 1):
                    print(f"  [{i}] {s.name}")
                print(Fore.CYAN + f"Select snippet to edit [1-{len(p.snippets)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.snippets):
                    idx = int(sel) - 1
                    s = p.snippets[idx]
                    print(Fore.CYAN + f"New Name [{s.name}]: ", end="")
                    n_name = input().strip()
                    print(Fore.CYAN + f"Edit content? [y/N]: ", end="")
                    if input().strip().lower() == 'y':
                        print(Fore.WHITE + "Enter content lines (type 'END' to finish):")
                        c_lines = []
                        while True:
                            l = input()
                            if l.strip() == 'END':
                                break
                            c_lines.append(l)
                        n_content = "\n".join(c_lines).strip()
                        self.service.update_snippet(idx, name=n_name or s.name, content=n_content or s.content)
                    else:
                        if n_name:
                            self.service.update_snippet(idx, name=n_name)
                    print_success("Snippet updated successfully.")
                else:
                    self.menu.show_error("Invalid selection.")

            elif choice == '4':
                # Delete snippet
                if not p.snippets:
                    self.menu.show_error("No snippets to delete.")
                    continue
                for i, s in enumerate(p.snippets, 1):
                    print(f"  [{i}] {s.name}")
                print(Fore.CYAN + f"Select snippet to delete [1-{len(p.snippets)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.snippets):
                    self.service.delete_snippet(int(sel) - 1)
                    print_success("Snippet deleted successfully.")
                else:
                    self.menu.show_error("Invalid selection.")

            elif choice == '5':
                # Preview snippet
                if not p.snippets:
                    self.menu.show_error("No snippets to preview.")
                    continue
                for i, s in enumerate(p.snippets, 1):
                    print(f"  [{i}] {s.name}")
                print(Fore.CYAN + f"Select snippet to preview [1-{len(p.snippets)}]: ", end="")
                sel = input().strip()
                if sel.isdigit() and 1 <= int(sel) <= len(p.snippets):
                    idx = int(sel) - 1
                    s = p.snippets[idx]
                    rendered = self.resolver.resolveTemplate(s.content)
                    print(Fore.CYAN + Style.BRIGHT + "\nPreview")
                    print(Fore.CYAN + "-" * 50)
                    print(Fore.WHITE + rendered)
                    print(Fore.CYAN + "-" * 50)
                    print(Fore.CYAN + "Press Enter to return: ", end="")
                    input()
                else:
                    self.menu.show_error("Invalid selection.")
            else:
                self.menu.show_error("Invalid choice.")

    # ── 10. Privacy & Security ─────────────────────────────────────────────────

    def handle_privacy_menu(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Privacy & Security")
            req_conf_str = "Enabled" if p.privacy.require_confirmation else "Disabled"
            lock_str = "Locked" if p.privacy.is_locked else "Unlocked"

            lines = [
                f"[1] Auto-use Profile Information",
                f"[2] Sensitive Information Protection",
                f"[3] Require Confirmation: {req_conf_str}",
                f"[4] View Stored Fields",
                f"[5] Export Profile",
                f"[6] Import Profile",
                f"[7] Delete Profile Data",
                f"[8] Lock Profile: {lock_str}",
                "",
                "[b] Back",
            ]
            self._print_centered_lines(lines)
            print()
            choice = self._prompt_choice("Choose an option [1-8, b]: ")
            if choice == 'b':
                break

            if choice == '1':
                self._manage_auto_use_flow()
            elif choice == '2':
                self._manage_sensitivity_flow()
            elif choice == '3':
                self.service.toggle_require_confirmation()
                state = "enabled" if self.service.get_profile().privacy.require_confirmation else "disabled"
                print_success(f"Confirmation requirement {state}.")
            elif choice == '4':
                self._view_stored_fields_flow()
            elif choice == '5':
                self._export_profile_flow()
            elif choice == '6':
                self._import_profile_flow()
            elif choice == '7':
                self._delete_profile_flow()
            elif choice == '8':
                self.service.toggle_lock()
                state = "locked" if self.service.get_profile().privacy.is_locked else "unlocked"
                print_success(f"Profile is now {state}.")
            else:
                self.menu.show_error("Invalid choice.")

    def _manage_auto_use_flow(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Auto-use Profile Information")
            print(Fore.CYAN + "Toggle automatic usage for each field:\n")
            fields_list = list(p.privacy.auto_use_fields.items())
            for idx, (k, enabled) in enumerate(fields_list, 1):
                box = "[✓]" if enabled else "[ ]"
                print(f"  {Fore.GREEN}[{idx}]{Style.RESET_ALL} {box} {k.capitalize()}")
            print(f"\n  {Fore.WHITE}[b] Done")
            print()
            print(Fore.CYAN + f"Select field to toggle [1-{len(fields_list)}, b]: ", end="")
            sel = input().strip().lower()
            if sel == 'b':
                break
            if sel.isdigit() and 1 <= int(sel) <= len(fields_list):
                key_to_toggle = fields_list[int(sel) - 1][0]
                self.service.toggle_auto_use(key_to_toggle)
            else:
                self.menu.show_error("Invalid selection.")

    def _manage_sensitivity_flow(self):
        while True:
            p = self.service.get_profile()
            self._print_header("Sensitive Information Protection")
            all_fields = ['phone', 'alternatePhone', 'address', 'dateOfBirth', 'studentId']
            # Include custom fields
            for c in p.custom_fields:
                if c.key not in all_fields:
                    all_fields.append(c.key)

            print(Fore.CYAN + "Sensitive fields require explicit confirmation before insertion:\n")
            for idx, f in enumerate(all_fields, 1):
                is_sens = f in p.privacy.sensitive_fields or (any(c.key == f and c.sensitivity for c in p.custom_fields))
                flag = "[✓ Sensitive]" if is_sens else "[  Normal   ]"
                print(f"  {Fore.GREEN}[{idx}]{Style.RESET_ALL} {flag} {f.replace('_', ' ').capitalize()}")

            print(f"\n  {Fore.WHITE}[b] Done")
            print()
            print(Fore.CYAN + f"Select field to toggle sensitivity [1-{len(all_fields)}, b]: ", end="")
            sel = input().strip().lower()
            if sel == 'b':
                break
            if sel.isdigit() and 1 <= int(sel) <= len(all_fields):
                field_name = all_fields[int(sel) - 1]
                is_currently_sens = field_name in p.privacy.sensitive_fields
                self.service.set_sensitive(field_name, not is_currently_sens)
                # Also update custom field if applicable
                for c in p.custom_fields:
                    if c.key == field_name:
                        c.sensitivity = not is_currently_sens
                        self.service.save_profile()
            else:
                self.menu.show_error("Invalid selection.")

    def _view_stored_fields_flow(self):
        p = self.service.get_profile()
        self._print_header("Stored Profile Fields")
        
        fields_display = [
            ("Full Name", p.basic.fullName, False),
            ("First Name", p.basic.firstName, False),
            ("Last Name", p.basic.lastName, False),
            ("Display Name", p.basic.displayName, False),
            ("Date of Birth", p.basic.dateOfBirth, True),
            ("Primary Email", p.contact.primaryEmail, False),
            ("Personal Email", p.contact.personalEmail, False),
            ("Work Email", p.contact.workEmail, False),
            ("Phone", p.contact.phone, True),
            ("Alternate Phone", p.contact.alternatePhone, True),
            ("Job Title", p.professional.jobTitle, False),
            ("Company", p.professional.company, False),
            ("Department", p.professional.department, False),
            ("Experience", p.professional.experience, False),
            ("GitHub", p.professional.github, False),
            ("LinkedIn", p.professional.linkedin, False),
            ("Portfolio", p.professional.portfolio, False),
            ("Website", p.professional.website, False),
        ]

        for label, val, is_sens in fields_display:
            if not val:
                display_val = Fore.WHITE + Style.DIM + "(not set)"
            elif is_sens:
                display_val = Fore.YELLOW + "[Protected: Sensitive]"
            else:
                display_val = Fore.GREEN + str(val)
            print(f"  {Fore.CYAN}{label:<22}: {display_val}")

        if p.addresses:
            print(f"\n  {Fore.CYAN}Addresses ({len(p.addresses)}):")
            for a in p.addresses:
                print(f"    - {a.label}: {Fore.YELLOW}[Protected: Sensitive]")

        if p.education:
            print(f"\n  {Fore.CYAN}Education Records ({len(p.education)}):")
            for e in p.education:
                print(f"    - {e.institution} - {e.degree} ({e.year or 'N/A'})")

        if p.custom_fields:
            print(f"\n  {Fore.CYAN}Custom Fields ({len(p.custom_fields)}):")
            for c in p.custom_fields:
                v = Fore.YELLOW + "[Protected: Sensitive]" if c.sensitivity else Fore.GREEN + c.value
                print(f"    - {c.displayName}: {v}")

        print(Fore.CYAN + "\nPress Enter to return: ", end="")
        input()

    def _export_profile_flow(self):
        print(Fore.YELLOW + Style.BRIGHT + "\nExport personal profile?")
        print(Fore.YELLOW + "This file may contain sensitive information.")
        print(Fore.CYAN + "\n[y] Continue\n[n] Cancel")
        print(Fore.CYAN + "\nChoice: ", end="")
        if input().strip().lower() != 'y':
            print_info("Export cancelled.")
            return

        print(Fore.CYAN + "Export file path [./profile_export.json]: ", end="")
        f_path = input().strip() or "./profile_export.json"
        try:
            target = Path(f_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.service.export_profile_json(), encoding='utf-8')
            print_success(f"Profile exported successfully to {target}")
        except Exception as e:
            print_error(f"Export failed: {e}")

    def _import_profile_flow(self):
        print(Fore.CYAN + "\nEnter path to profile JSON file to import: ", end="")
        f_path = input().strip()
        if not f_path:
            return
        path = Path(f_path).resolve()
        if not path.exists():
            print_error(f"File not found: {path}")
            return

        try:
            content = path.read_text(encoding='utf-8')
        except Exception as e:
            print_error(f"Could not read file: {e}")
            return

        ok, preview_or_err, new_profile = self.service.import_profile_json(content)
        if not ok or not new_profile:
            print_error(f"Invalid profile file: {preview_or_err}")
            return

        print(Fore.CYAN + Style.BRIGHT + "\nProfile Import Preview:")
        print(Fore.CYAN + "-" * 40)
        print(Fore.WHITE + preview_or_err)
        print(Fore.CYAN + "-" * 40)
        print(Fore.YELLOW + "Warning: This will overwrite your existing profile data.")
        print(Fore.CYAN + "Confirm import? [y/N]: ", end="")
        if input().strip().lower() == 'y':
            if self.service.apply_import(new_profile):
                print_success("Profile imported successfully.")
            else:
                print_error("Failed to save imported profile.")
        else:
            print_info("Import cancelled.")

    def _delete_profile_flow(self):
        print(Fore.RED + Style.BRIGHT + "\nWARNING: This will erase all configured profile fields and snippets!")
        print(Fore.CYAN + "Are you sure you want to delete profile data? [y/N]: ", end="")
        if input().strip().lower() == 'y':
            self.service.reset_profile()
            print_success("Profile data reset to defaults.")
        else:
            print_info("Deletion cancelled.")

    # ── Helpers for editing fields ─────────────────────────────────────────────

    def _edit_single_field(self, label: str, current_val: str, validator, save_fn):
        if self.service.is_locked():
            self.menu.show_error("Profile is currently locked. Please unlock in Privacy & Security before editing.")
            return

        print(Fore.CYAN + f"\n{label}")
        print(Fore.WHITE + f"Current value: {current_val or '(not set)'}")

        while True:
            print(Fore.CYAN + "New value (press Enter to cancel): ")
            print(Fore.WHITE + "> ", end="")
            new_val = input().strip()
            if not new_val:
                print_info("Cancelled.")
                break

            ok, err = validator(new_val)
            if not ok:
                print(Fore.RED + f"✗ {err}\n")
                continue

            if save_fn(new_val):
                print_success(f"{label} updated successfully.")
            else:
                print_error("Failed to save value.")
            break

    def _clear_menu(self, options_list: List[tuple]):
        print(Fore.CYAN + "\nSelect field to clear:")
        for num, label, _ in options_list:
            print(f"  [{num}] {label}")
        print(f"  [b] Cancel")
        print(Fore.CYAN + "Select: ", end="")
        sel = input().strip().lower()
        if sel == 'b':
            return
        match = next((item for item in options_list if item[0] == sel), None)
        if match:
            match[2]()
            print_success(f"{match[1]} cleared.")
        else:
            self.menu.show_error("Invalid selection.")

    # ── 11. Gmail Compose Integration ──────────────────────────────────────────

    def handle_compose_profile_assistance(self, subject: str, body: str, tmp_path: str) -> str:
        """
        Provides profile-aware suggestions and insertion options during Gmail Compose.
        Returns the updated body string.
        """
        combined_context = f"{subject}\n{body}"
        suggestions = self.resolver.getSuggestions(combined_context)

        # 1. Show context-aware suggestions if matched
        if suggestions:
            print(Fore.CYAN + Style.BRIGHT + "\nSuggested Profile Information")
            print(Fore.CYAN + "-" * 50)
            print(Fore.WHITE + "This email may benefit from:\n")
            for idx, item in enumerate(suggestions, 1):
                sens_tag = " (Sensitive)" if item['is_sensitive'] else ""
                print(f"  {Fore.GREEN}[{idx}]{Style.RESET_ALL} {item['display_name']}: {item['value']}{sens_tag}")

            print(f"\n  {Fore.WHITE}[c] Continue without adding")
            print(f"  {Fore.WHITE}[b] Back")
            print()
            print(Fore.CYAN + f"Select item to insert, or [c] to continue: ", end="")
            s_choice = input().strip().lower()

            if s_choice.isdigit() and 1 <= int(s_choice) <= len(suggestions):
                selected = suggestions[int(s_choice) - 1]
                # Confirmation for sensitive data
                if selected['is_sensitive'] and self.service.get_profile().privacy.require_confirmation:
                    print(Fore.YELLOW + f"Include sensitive field '{selected['display_name']}'? [y/N]: ", end="")
                    if input().strip().lower() != 'y':
                        print_info("Skipped adding sensitive field.")
                        return body

                body = self._append_to_body(body, f"\n{selected['display_name']}: {selected['value']}")
                self._save_body_tmp(tmp_path, body)
                print_success(f"Inserted {selected['display_name']} into email body.")
                return body

        # 2. Provide direct insertion options
        print(Fore.CYAN + Style.BRIGHT + "\nProfile Assistance (optional)")
        print(Fore.CYAN + "-" * 50)
        print(Fore.WHITE + "[1] Insert Profile Information")
        print(Fore.WHITE + "[2] Insert Profile Snippet")
        print(Fore.WHITE + "[3] Continue")
        print()
        print(Fore.CYAN + "Select [1-3, default 3]: ", end="")
        c_choice = input().strip()

        if c_choice == '1':
            body = self._show_insert_profile_info_flow(body, tmp_path)
        elif c_choice == '2':
            body = self._show_insert_snippet_flow(body, tmp_path)

        return body

    def _show_insert_profile_info_flow(self, body: str, tmp_path: str) -> str:
        # Collect all fields with values
        available_fields = [
            ("Name", "name"),
            ("Email", "email"),
            ("Phone", "phone"),
            ("College", "college"),
            ("Degree", "degree"),
            ("Department", "department"),
            ("GitHub", "github"),
            ("LinkedIn", "linkedin"),
            ("Portfolio", "portfolio"),
            ("Website", "website"),
            ("Company", "company"),
            ("Job Title", "job_title"),
            ("Address", "address"),
        ]

        populated = []
        for label, key in available_fields:
            val = self.resolver.get(key)
            if val:
                populated.append((label, key, str(val)))

        if not populated:
            print_info("No profile fields are configured with values yet.")
            return body

        print(Fore.CYAN + Style.BRIGHT + "\nProfile Information")
        print(Fore.CYAN + "-" * 50)
        for idx, (lbl, key, val) in enumerate(populated, 1):
            sens_tag = " (Sensitive)" if self.resolver.isSensitive(key) else ""
            print(f"  {Fore.GREEN}[{idx}]{Style.RESET_ALL} {lbl}: {val}{sens_tag}")

        print(f"\n  {Fore.WHITE}[10] Insert Multiple")
        print(f"  {Fore.WHITE}[b] Back")
        print()
        print(Fore.CYAN + f"Select field to insert [1-{len(populated)}, 10, b]: ", end="")
        sel = input().strip().lower()

        if sel == 'b':
            return body
        elif sel == '10':
            print(Fore.CYAN + f"Enter field numbers separated by comma (e.g. 1, 4, 7): ", end="")
            nums = input().strip().split(',')
            inserted_text = []
            for n in nums:
                n = n.strip()
                if n.isdigit() and 1 <= int(n) <= len(populated):
                    lbl, key, val = populated[int(n) - 1]
                    if self.resolver.isSensitive(key) and self.service.get_profile().privacy.require_confirmation:
                        print(Fore.YELLOW + f"Include sensitive field '{lbl}'? [y/N]: ", end="")
                        if input().strip().lower() != 'y':
                            continue
                    inserted_text.append(f"{lbl}: {val}")
            if inserted_text:
                body = self._append_to_body(body, "\n" + "\n".join(inserted_text))
                self._save_body_tmp(tmp_path, body)
                print_success(f"Inserted {len(inserted_text)} profile fields into email body.")
            return body

        elif sel.isdigit() and 1 <= int(sel) <= len(populated):
            lbl, key, val = populated[int(sel) - 1]
            if self.resolver.isSensitive(key) and self.service.get_profile().privacy.require_confirmation:
                print(Fore.YELLOW + f"Include sensitive field '{lbl}'? [y/N]: ", end="")
                if input().strip().lower() != 'y':
                    print_info("Skipped adding sensitive field.")
                    return body

            body = self._append_to_body(body, f"\n{lbl}: {val}")
            self._save_body_tmp(tmp_path, body)
            print_success(f"Inserted {lbl} into email body.")
            return body

        return body

    def _show_insert_snippet_flow(self, body: str, tmp_path: str) -> str:
        p = self.service.get_profile()
        if not p.snippets:
            print_info("No profile snippets created yet. Add snippets under Personal Profile -> Profile Snippets.")
            return body

        print(Fore.CYAN + Style.BRIGHT + "\nProfile Snippets")
        print(Fore.CYAN + "-" * 50)
        for idx, s in enumerate(p.snippets, 1):
            print(f"  {Fore.GREEN}[{idx}]{Style.RESET_ALL} {s.name}")

        print(f"\n  {Fore.WHITE}[b] Back")
        print()
        print(Fore.CYAN + f"Select snippet to insert [1-{len(p.snippets)}, b]: ", end="")
        sel = input().strip().lower()
        if sel == 'b':
            return body

        if sel.isdigit() and 1 <= int(sel) <= len(p.snippets):
            snip = p.snippets[int(sel) - 1]
            rendered = self.resolver.resolveTemplate(snip.content)
            body = self._append_to_body(body, "\n" + rendered)
            self._save_body_tmp(tmp_path, body)
            print_success(f"Inserted snippet '{snip.name}' into email body.")
        return body

    def _append_to_body(self, body: str, addition: str) -> str:
        if not body:
            return addition.strip()
        return body + "\n" + addition

    def _save_body_tmp(self, tmp_path: str, body: str):
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(body)
        except Exception:
            pass
