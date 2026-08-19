"""FoodSeg103 category names and mapping to nutrition.py FoodProfile keys.

FoodSeg103 has 103 food categories (ID 1-103, 0=background).
YOLO class IDs are 0-102 (FoodSeg103 ID minus 1).
"""
from __future__ import annotations

import json
from pathlib import Path


# Actual FoodSeg103 categories from id2label.json (verified from trained model)
FOODSEG_CATEGORIES: dict[int, str] = {
    1: "candy", 2: "egg tart", 3: "french fries", 4: "chocolate",
    5: "biscuit", 6: "popcorn", 7: "pudding", 8: "ice cream",
    9: "cheese butter", 10: "cake", 11: "wine", 12: "milkshake",
    13: "coffee", 14: "juice", 15: "milk", 16: "tea",
    17: "almond", 18: "red beans", 19: "cashew", 20: "dried cranberries",
    21: "soy", 22: "walnut", 23: "peanut", 24: "egg",
    25: "apple", 26: "date", 27: "apricot", 28: "avocado",
    29: "banana", 30: "strawberry", 31: "cherry", 32: "blueberry",
    33: "raspberry", 34: "mango", 35: "olives", 36: "peach",
    37: "lemon", 38: "pear", 39: "fig", 40: "pineapple",
    41: "grape", 42: "kiwi", 43: "melon", 44: "orange",
    45: "watermelon", 46: "steak", 47: "pork", 48: "chicken duck",
    49: "sausage", 50: "fried meat", 51: "lamb", 52: "sauce",
    53: "crab", 54: "fish", 55: "shellfish", 56: "shrimp",
    57: "soup", 58: "bread", 59: "corn", 60: "hamburg",
    61: "pizza", 62: "hanamaki baozi", 63: "wonton dumplings", 64: "pasta",
    65: "noodles", 66: "rice", 67: "pie", 68: "tofu",
    69: "eggplant", 70: "potato", 71: "garlic", 72: "cauliflower",
    73: "tomato", 74: "kelp", 75: "seaweed", 76: "spring onion",
    77: "rape", 78: "ginger", 79: "okra", 80: "lettuce",
    81: "pumpkin", 82: "cucumber", 83: "white radish", 84: "carrot",
    85: "asparagus", 86: "bamboo shoots", 87: "broccoli", 88: "celery stick",
    89: "cilantro mint", 90: "snow peas", 91: "cabbage", 92: "bean sprouts",
    93: "onion", 94: "pepper", 95: "green beans", 96: "French beans",
    97: "king oyster mushroom", 98: "shiitake", 99: "enoki mushroom", 100: "oyster mushroom",
    101: "white button mushroom", 102: "salad", 103: "other ingredients",
}

# Aliases for backward compatibility
FALLBACK_CATEGORIES = FOODSEG_CATEGORIES


def load_categories(data_dir: str | Path) -> dict[int, str]:
    """Load category names from id2label.json in the dataset directory.

    Falls back to FOODSEG_CATEGORIES if file not found.
    """
    data_dir = Path(data_dir)
    f = data_dir / "id2label.json"
    if f.exists():
        with open(f, encoding="utf-8") as fp:
            raw = json.load(fp)
        cats = {int(k): v for k, v in raw.items()}
        if cats:
            print(f"从 id2label.json 加载了 {len(cats)} 个类别")
            return cats
    print(f"使用内置类别列表 ({len(FOODSEG_CATEGORIES)} 个类别)")
    return FOODSEG_CATEGORIES


# Mapping from FoodSeg103 category names to nutrition.py FoodProfile keys.
# Unmapped categories use "unknown_food" as fallback.
FOODSEG_TO_NUTRITION_KEY: dict[str, str] = {
    # Sweets and snacks
    "candy": "candy",
    "egg tart": "egg_tart",
    "french fries": "chips",
    "chocolate": "chocolate",
    "biscuit": "biscuit",
    "popcorn": "packaged_snack",
    "pudding": "cake",
    "ice cream": "cream_cake",
    "cheese butter": "dried_tofu",
    "cake": "cake",
    "pie": "cake",
    # Beverages (mapped to unknown_food - liquid, hard to estimate)
    "wine": "unknown_food",
    "milkshake": "unknown_food",
    "coffee": "unknown_food",
    "juice": "unknown_food",
    "milk": "soybean",
    "tea": "unknown_food",
    # Nuts and beans
    "almond": "packaged_snack",
    "red beans": "soybean",
    "cashew": "packaged_snack",
    "dried cranberries": "packaged_snack",
    "soy": "soybean",
    "walnut": "packaged_snack",
    "peanut": "packaged_snack",
    # Egg
    "egg": "egg",
    # Fruits
    "apple": "apple",
    "date": "apple",
    "apricot": "apple",
    "avocado": "apple",
    "banana": "banana",
    "strawberry": "apple",
    "cherry": "apple",
    "blueberry": "apple",
    "raspberry": "apple",
    "mango": "watermelon",
    "olives": "packaged_snack",
    "peach": "apple",
    "lemon": "orange",
    "pear": "apple",
    "fig": "apple",
    "pineapple": "watermelon",
    "grape": "apple",
    "kiwi": "apple",
    "melon": "watermelon",
    "orange": "orange",
    "watermelon": "watermelon",
    # Meats
    "steak": "beef",
    "pork": "pork_lean",
    "chicken duck": "chicken",
    "sausage": "pork_belly",
    "fried meat": "pork_belly",
    "lamb": "lamb",
    # Seafood
    "crab": "shrimp",
    "fish": "fish",
    "shellfish": "shrimp",
    "shrimp": "shrimp",
    # Soup
    "soup": "porridge",
    # Staples
    "bread": "bread",
    "corn": "corn",
    "hamburg": "bread",
    "pizza": "fried_rice",
    "hanamaki baozi": "steamed_bun",
    "wonton dumplings": "dumpling",
    "pasta": "wheat_noodles",
    "noodles": "wheat_noodles",
    "rice": "rice",
    # Tofu
    "tofu": "tofu",
    # Vegetables
    "eggplant": "eggplant",
    "potato": "potato",
    "garlic": "onion",
    "cauliflower": "cauliflower",
    "tomato": "tomato",
    "kelp": "unknown_food",
    "seaweed": "unknown_food",
    "spring onion": "onion",
    "rape": "bok_choy",
    "ginger": "unknown_food",
    "okra": "green_bean",
    "lettuce": "lettuce",
    "pumpkin": "pumpkin",
    "cucumber": "cucumber",
    "white radish": "bok_choy",
    "carrot": "carrot",
    "asparagus": "celery",
    "bamboo shoots": "bamboo_shoot",
    "broccoli": "broccoli",
    "celery stick": "celery",
    "cilantro mint": "bok_choy",
    "snow peas": "snow_pea",
    "cabbage": "cabbage",
    "bean sprouts": "bean_sprout",
    "onion": "onion",
    "pepper": "bell_pepper",
    "green beans": "green_bean",
    "French beans": "green_bean",
    # Mushrooms
    "king oyster mushroom": "mushroom",
    "shiitake": "shiitake",
    "enoki mushroom": "enoki",
    "oyster mushroom": "mushroom",
    "white button mushroom": "mushroom",
    # Mixed
    "salad": "stir_fried_greens",
    "sauce": "unknown_food",
    "other ingredients": "unknown_food",
}


def get_nutrition_key(foodseg_name: str) -> str:
    """Map a FoodSeg103 category name to a nutrition.py FoodProfile key.

    Returns "unknown_food" if no mapping exists.
    """
    key = FOODSEG_TO_NUTRITION_KEY.get(foodseg_name)
    if key:
        return key
    lower = foodseg_name.lower()
    return FOODSEG_TO_NUTRITION_KEY.get(lower, "unknown_food")


def build_mapping_report(categories: dict[int, str]) -> str:
    """Generate a report showing which FoodSeg103 categories have nutrition mappings."""
    lines = ["FoodSeg103 -> nutrition.py 映射报告", "=" * 50]
    mapped = 0
    unmapped = 0
    for cat_id, name in sorted(categories.items()):
        if cat_id == 0:
            continue
        key = get_nutrition_key(name)
        if key != "unknown_food":
            lines.append(f"  {cat_id:3d}. {name:25s} -> {key}")
            mapped += 1
        else:
            lines.append(f"  {cat_id:3d}. {name:25s} -> (未映射)")
            unmapped += 1
    lines.append(f"\n已映射: {mapped}, 未映射: {unmapped}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "../../datasets/FoodSeg103"
    cats = load_categories(data_dir)
    print(build_mapping_report(cats))
