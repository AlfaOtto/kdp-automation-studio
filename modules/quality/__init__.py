"""
Module 2b — Quality Validator + Auto-Fixer for generated KDP products.

Goal: never push a broken product to KDP. Before publication, the Validator
scans the product folder and produces:
  - quality_score (0-100)
  - issues: list of {severity, code, message, fix_available}
  - auto-fixable issues are tagged so the UI can offer a 🔧 button.

Public API:
  validate_product(product_folder) → ValidationReport
  auto_fix_product(product_folder, anthropic_key, openai_key) → FixReport
"""
