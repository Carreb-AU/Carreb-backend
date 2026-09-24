import time
from typing import List
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Master Command: Synchronize all 29 sheets across both Excel workbooks into Carreb DB"

    ALL_SHEET_COMMANDS = [
        # 1. Platform & Policy Foundation (Sheets 8-15)
        ("sync_sheet_08_category_scoring_bounds", "CategoryScoringBounds"),
        ("sync_sheet_09_finance_defaults", "FinanceDefaults"),
        ("sync_sheet_10_platform_defaults", "PlatformDefaults"),
        ("sync_sheet_11_depreciation_lookups", "DepreciationLookups"),
        ("sync_sheet_12_changes_from_prior_build", "ChangesFromPriorBuild"),
        ("sync_sheet_13_v634_summary", "v6.3.4 Summary"),
        ("sync_sheet_14_acl_disclaimer", "ACL_Disclaimer"),
        ("sync_sheet_15_fcai_category_registry", "FCAICategoryRegistry"),

        # 2. State & Component Cost Benchmarks (Sheets 16-23)
        ("sync_sheet_16_fuel_electricity_prices", "FuelElectricityPrices"),
        ("sync_sheet_17_insurance_defaults", "InsuranceDefaults"),
        ("sync_sheet_18_registration_defaults", "RegistrationDefaults"),
        ("sync_sheet_19_maintenance_defaults", "MaintenanceDefaults"),
        ("sync_sheet_20_tyre_cost_defaults", "TyreCostDefaults"),
        ("sync_sheet_21_energy_type_cost_modifiers", "EnergyTypeCostModifiers"),
        ("sync_sheet_22_annual_km_by_category", "AnnualKMByCategory"),
        ("sync_sheet_23_coo_benchmark_audit", "COOBenchmarkAudit"),

        # 3. Policy, Compliance & Architectural Traceability (Sheets 25-29)
        ("sync_sheet_25_sources_index", "_Sources_Index"),
        ("sync_sheet_26_nga_emission_factors", "NGA_EmissionFactors"),
        ("sync_sheet_27_driveaway_tax_parameters", "DriveawayTaxParameters"),
        ("sync_sheet_28_policy_update_log", "v6.4 Policy Update Log"),
        ("sync_sheet_29_devspec", "DevSpec_TraceMap"),

        # 4. Vehicle Catalogue Datasets (Sheets 5, 6, 1)
        ("sync_sheet_05_v634_data", "v6.3.4 Data (Vehicle Catalogue)"),
        ("sync_sheet_06_new_vehicles_fy26", "New Vehicles FY26"),
        ("sync_sheet_01_gapfill", "Market Gap-Fill Data"),

        # 5. Granular Vehicle Breakdown & Canonical Scores (Sheets 7, 24)
        ("sync_sheet_07_core_score_canonical", "VehicleCOREScore_Canonical"),
        ("sync_sheet_24_coo_component_breakdown", "COO_Component_Breakdown (8,776 rows)"),

        # 6. Documentation & Template Reference (Sheets 2, 3, 4)
        ("sync_sheet_02_field_defs", "Lists (Gap-Fill Dropdowns)"),
        ("sync_sheet_03_brand_tracker", "Brand Tracker"),
        ("sync_sheet_04_readme", "README Documentation"),
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate execution without modifying the database",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear tables before ingestion where supported",
        )
        parser.add_argument(
            "--sheets",
            type=str,
            default="",
            help="Optional comma-separated list of command suffixes or sheet numbers (e.g. '05,08,10')",
        )

    def handle(self, *args, **options):
        is_dry_run = options["dry_run"]
        clear = options["clear"]
        sheets_filter = [s.strip() for s in options["sheets"].split(",") if s.strip()]

        self.stdout.write("=" * 80)
        self.stdout.write("CARREB MASTER SYNC ENGINE: 29 SHEETS SEQUENTIAL INGESTION")
        self.stdout.write("=" * 80)

        total_start = time.time()
        successes, failures = [], []

        for cmd_name, label in self.ALL_SHEET_COMMANDS:
            # Check filter if provided
            if sheets_filter:
                match = any(sf in cmd_name for sf in sheets_filter)
                if not match:
                    continue

            self.stdout.write(f"\n>>> Running [{cmd_name}] ({label})...")
            step_start = time.time()
            try:
                cmd_kwargs = {}
                if is_dry_run:
                    cmd_kwargs["dry_run"] = True
                if clear:
                    cmd_kwargs["clear"] = True

                call_command(cmd_name, **cmd_kwargs)
                elapsed = time.time() - step_start
                successes.append((cmd_name, label, elapsed))
            except Exception as e:
                elapsed = time.time() - step_start
                failures.append((cmd_name, label, str(e), elapsed))
                self.stderr.write(self.style.ERROR(f"Failed [{cmd_name}]: {e}"))

        total_time = time.time() - total_start
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(f"MASTER SYNC SUMMARY: Completed in {total_time:.2f}s")
        self.stdout.write(f"Passed: {len(successes)} / {len(successes) + len(failures)}")
        if failures:
            self.stdout.write(self.style.ERROR(f"Failed: {len(failures)}"))
            for cmd_name, label, err, _ in failures:
                self.stdout.write(self.style.ERROR(f"  - {cmd_name}: {err}"))
        else:
            self.stdout.write(self.style.SUCCESS("All scheduled sheet commands completed successfully!"))
        self.stdout.write("=" * 80)
