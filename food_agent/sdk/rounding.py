"""
USDA/FDA Nutrition Rounding Rules Implementation.
References: 21 CFR 101.9
"""
from typing import Dict, Any, Union

class NutritionRounder:
    """
    Implements FDA rounding rules for nutrition labeling.
    Used for displaying formatted output.
    """

    @staticmethod
    def round_calories(val: float) -> int:
        """
        Calories:
        < 5: 0
        <= 50: nearest 5
        > 50: nearest 10
        """
        if val < 5:
            return 0
        if val <= 50:
            return int(round(val / 5) * 5)
        return int(round(val / 10) * 10)

    @staticmethod
    def round_fat(val: float) -> float:
        """
        Total Fat, Saturated Fat, Trans Fat:
        < 0.5: 0
        < 5: nearest 0.5
        >= 5: nearest 1
        """
        if val < 0.5:
            return 0.0
        if val < 5:
            # Round to nearest 0.5
            return round(val * 2) / 2
        return float(round(val))

    @staticmethod
    def round_cholesterol(val: float) -> int:
        """
        Cholesterol:
        < 2: 0
        2-5: "less than 5" -> We treat as 0 or 5 for numeric consistency. 
             (Aligning with >5 rule, we'll round to nearest 5 starting at 2).
        > 5: nearest 5
        """
        if val < 2:
            return 0
        return int(round(val / 5) * 5)

    @staticmethod
    def round_sodium(val: float) -> int:
        """
        Sodium:
        < 5: 0
        5 - 140: nearest 5
        > 140: nearest 10
        """
        if val < 5:
            return 0
        if val <= 140:
            return int(round(val / 5) * 5)
        return int(round(val / 10) * 10)
    
    @staticmethod
    def round_potassium(val: float) -> int:
        """
        Potassium:
        FDA 2016 rules: < 5 -> 0, 5-140 -> nearest 5, > 140 -> nearest 10.
        """
        return NutritionRounder.round_sodium(val)

    @staticmethod
    def round_carb_fiber_sugar_protein(val: float) -> int:
        """
        Total Carb, Fiber, Sugar, Protein:
        < 0.5: 0
        < 1: "less than 1 g" -> We treat as 0 or 1.
             (Standard is nearest 1g for anything >= 0.5).
        >= 1: nearest 1
        """
        if val < 0.5:
            return 0
        return int(round(val))

    @staticmethod
    def round_generic(val: float) -> float:
        """
        Generic rounding for vitamins/minerals not specified: 
        Default to 1 decimal place.
        """
        return round(val, 1)

    @classmethod
    def round_all(cls, nutrients: Dict[str, float]) -> Dict[str, Union[float, int]]:
        """
        Apply rounding rules to a dictionary of nutrients.
        """
        rounded = {}
        for key, val in nutrients.items():
            if val is None:
                continue
                
            k = key.lower()
            if 'calor' in k: # calories
                rounded[key] = cls.round_calories(val)
            elif 'fat' in k: # total fat, sat fat, etc.
                rounded[key] = cls.round_fat(val)
            elif 'cholest' in k:
                rounded[key] = cls.round_cholesterol(val)
            elif 'sodium' in k:
                rounded[key] = cls.round_sodium(val)
            elif 'potass' in k:
                rounded[key] = cls.round_potassium(val)
            elif any(x in k for x in ['carb', 'fiber', 'sugar', 'protein']):
                rounded[key] = cls.round_carb_fiber_sugar_protein(val)
            else:
                rounded[key] = cls.round_generic(val)
        return rounded
