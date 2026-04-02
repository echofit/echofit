# Design Decisions

## Nutrition Data Precision & Rounding

### 1. Problem Statement
Nutritional data typically arrives with high precision from calculations (e.g., `1.97` servings * `105` kcal = `206.85` kcal). However, users expect to see values that align with standard nutrition labels.

We needed to decide:
*   **Where to round?** (Backend SDK vs. Frontend Client)
*   **How to sum?** (Sum of rounded items vs. Rounded sum of precise items)
*   **What rules to follow?** (FDA 21 CFR 101.9)

### 2. Research & Standards

#### FDA Rounding Rules (21 CFR 101.9)
Official rules for nutrition labeling:
*   **Calories:** <5 → 0; ≤50 → nearest 5; >50 → nearest 10.
*   **Fat:** <0.5g → 0; <5g → nearest 0.5g; >5g → nearest 1g.
*   **Carbs/Protein:** <0.5g → 0; ≥1g → nearest 1g.
*   **Sodium/Potassium:** <5mg → 0; 5-140mg → nearest 5mg; >140mg → nearest 10mg.

#### Industry Practice
*   **Leading Apps (e.g., MyFitnessPal):** Sum the precise values internally and round the final display. This prevents significant "drift" in daily totals while keeping the UI clean.
*   **Discrepancies:** It is an industry-standard trade-off that `Sum(Rounded Items) != Rounded Total`. Accuracy of the total is prioritized over the visual sum of rounded parts.

### 3. Key Decisions

#### Decision 1: Backend as "Source of Truth" for Presentation
The Client/UI should not be responsible for understanding nutritional labeling regulations.
*   **Outcome:** The `get_food_log` tool returns **pre-rounded** values for both individual items and daily totals.
*   **Benefit:** Any client (CLI, Web, Mobile) displays consistent, compliant data without duplicating logic.

#### Decision 2: Rounded Sum of Precise Items
To maximize accuracy for daily totals:
1.  Calculate precise nutrition for each consumed item.
2.  Sum these precise values to get the `Daily Total`.
3.  Apply FDA rounding rules to the `Daily Total` for the final response.

### 4. Implementation
*   **Module:** `echofit.diet.rounding.NutritionRounder` implements the logic.
*   **Integration:** `DietSDK.get_food_log` applies this rounder to the final output.