from __future__ import annotations

from dataclasses import asdict, dataclass

from backend.models.schemas import Nutrition


@dataclass(frozen=True)
class FoodProfile:
    key: str
    display_name: str
    category: str
    density_g_per_ml: float
    density_std_g_per_ml: float
    calories_kcal_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    fiber_g_per_100g: float = 0
    sodium_mg_per_100g: float = 0


@dataclass(frozen=True)
class CookingAdjustment:
    key: str
    display_name: str
    calories_delta_per_100g: float = 0
    fat_delta_per_100g: float = 0
    carbs_delta_per_100g: float = 0
    sodium_delta_per_100g: float = 0


def f(
    key: str,
    name: str,
    category: str,
    density: float,
    density_std: float,
    kcal: float,
    protein: float,
    carbs: float,
    fat: float,
    fiber: float = 0,
    sodium: float = 0,
) -> FoodProfile:
    return FoodProfile(key, name, category, density, density_std, kcal, protein, carbs, fat, fiber, sodium)


COOKING_METHODS: dict[str, CookingAdjustment] = {
    "unknown": CookingAdjustment("unknown", "未识别"),
    "raw_light": CookingAdjustment("raw_light", "少油/原味"),
    "boiled_steamed": CookingAdjustment("boiled_steamed", "水煮/清蒸"),
    "stir_fried": CookingAdjustment("stir_fried", "炒制", calories_delta_per_100g=65, fat_delta_per_100g=6, sodium_delta_per_100g=120),
    "pan_fried": CookingAdjustment("pan_fried", "煎制", calories_delta_per_100g=95, fat_delta_per_100g=8, sodium_delta_per_100g=140),
    "deep_fried": CookingAdjustment("deep_fried", "炸制", calories_delta_per_100g=120, fat_delta_per_100g=10, carbs_delta_per_100g=7, sodium_delta_per_100g=180),
    "braised": CookingAdjustment("braised", "红烧/卤制", calories_delta_per_100g=45, fat_delta_per_100g=3, carbs_delta_per_100g=3, sodium_delta_per_100g=220),
    "roasted": CookingAdjustment("roasted", "烤制", calories_delta_per_100g=35, fat_delta_per_100g=2, sodium_delta_per_100g=90),
    "baked": CookingAdjustment("baked", "烘焙", sodium_delta_per_100g=40),
}


# Approximate per-100g values for demo validation. They are normalized for this
# MVP's density -> weight -> nutrition pipeline and should not replace weighing.
FOOD_PROFILES: dict[str, FoodProfile] = {
    # Staples
    "rice": f("rice", "米饭", "主食", 0.72, 0.08, 116, 2.6, 25.9, 0.3, 0.4, 1),
    "brown_rice": f("brown_rice", "糙米饭", "主食", 0.74, 0.08, 111, 2.6, 23.0, 0.9, 1.8, 5),
    "millet_porridge": f("millet_porridge", "小米粥", "主食", 0.98, 0.05, 46, 1.4, 9.4, 0.4, 0.5, 3),
    "porridge": f("porridge", "白粥", "主食", 0.99, 0.04, 38, 0.8, 8.4, 0.1, 0.2, 2),
    "wheat_noodles": f("wheat_noodles", "面条", "主食", 0.78, 0.08, 138, 4.5, 25.0, 2.1, 1.2, 5),
    "rice_noodles": f("rice_noodles", "米粉", "主食", 0.76, 0.08, 109, 1.8, 24.9, 0.2, 0.8, 4),
    "steamed_bun": f("steamed_bun", "馒头", "主食", 0.45, 0.07, 223, 7.0, 47.0, 1.1, 1.7, 190),
    "dumpling": f("dumpling", "饺子", "主食", 0.82, 0.12, 197, 8.2, 26.0, 6.6, 1.8, 420),
    "wonton": f("wonton", "馄饨", "主食", 0.88, 0.10, 165, 7.0, 22.0, 5.5, 1.1, 390),
    "potato": f("potato", "土豆", "主食", 0.77, 0.08, 77, 2.0, 17.0, 0.1, 2.2, 6),
    "sweet_potato": f("sweet_potato", "红薯", "主食", 0.82, 0.09, 86, 1.6, 20.1, 0.1, 3.0, 55),
    "corn": f("corn", "玉米", "主食", 0.72, 0.09, 96, 3.4, 21.0, 1.5, 2.4, 1),
    "pumpkin": f("pumpkin", "南瓜", "蔬菜", 0.75, 0.08, 26, 1.0, 6.5, 0.1, 0.5, 1),
    "taro": f("taro", "芋头", "主食", 0.86, 0.09, 112, 1.5, 26.5, 0.2, 4.1, 11),
    "lotus_root": f("lotus_root", "莲藕", "蔬菜", 0.75, 0.08, 74, 2.6, 17.2, 0.1, 4.9, 40),
    # Proteins
    "chicken": f("chicken", "鸡胸肉", "蛋白质", 1.02, 0.06, 165, 31.0, 0, 3.6, 0, 74),
    "chicken_thigh": f("chicken_thigh", "鸡腿肉", "蛋白质", 1.02, 0.07, 209, 26.0, 0, 10.9, 0, 86),
    "duck": f("duck", "鸭肉", "蛋白质", 1.00, 0.08, 240, 19.0, 0, 18.0, 0, 74),
    "pork_lean": f("pork_lean", "瘦猪肉", "蛋白质", 1.04, 0.06, 143, 20.3, 0, 6.2, 0, 57),
    "pork_belly": f("pork_belly", "五花肉", "蛋白质", 0.96, 0.10, 518, 9.3, 0, 53.0, 0, 32),
    "beef": f("beef", "牛肉", "蛋白质", 1.05, 0.07, 250, 26.0, 0, 15.0, 0, 72),
    "lamb": f("lamb", "羊肉", "蛋白质", 1.04, 0.08, 258, 25.6, 0, 16.5, 0, 72),
    "fish": f("fish", "鱼肉", "蛋白质", 1.02, 0.07, 120, 20.0, 0, 4.0, 0, 70),
    "salmon": f("salmon", "三文鱼", "蛋白质", 1.01, 0.07, 208, 20.4, 0, 13.4, 0, 59),
    "shrimp": f("shrimp", "虾仁", "蛋白质", 1.03, 0.06, 99, 24.0, 0.2, 0.3, 0, 111),
    "egg": f("egg", "鸡蛋", "蛋白质", 0.95, 0.08, 143, 12.6, 1.1, 9.5, 0, 142),
    "tofu": f("tofu", "豆腐", "豆制品", 0.92, 0.08, 76, 8.1, 1.9, 4.8, 0.3, 7),
    "dried_tofu": f("dried_tofu", "豆干", "豆制品", 0.86, 0.08, 140, 16.2, 5.0, 7.0, 1.2, 380),
    "soybean": f("soybean", "黄豆", "豆制品", 0.78, 0.10, 173, 16.6, 9.9, 9.0, 6.0, 2),
    "edamame": f("edamame", "毛豆", "豆制品", 0.72, 0.09, 121, 11.9, 8.9, 5.2, 5.2, 6),
    # Leafy and green vegetables
    "broccoli": f("broccoli", "西兰花", "蔬菜", 0.40, 0.10, 34, 2.8, 6.6, 0.4, 2.6, 33),
    "cauliflower": f("cauliflower", "花菜", "蔬菜", 0.45, 0.10, 25, 1.9, 5.0, 0.3, 2.0, 30),
    "bok_choy": f("bok_choy", "小白菜", "蔬菜", 0.48, 0.10, 13, 1.5, 2.2, 0.2, 1.0, 65),
    "spinach": f("spinach", "菠菜", "蔬菜", 0.50, 0.10, 23, 2.9, 3.6, 0.4, 2.2, 79),
    "napa_cabbage": f("napa_cabbage", "大白菜", "蔬菜", 0.48, 0.10, 16, 1.2, 3.2, 0.2, 1.2, 18),
    "cabbage": f("cabbage", "卷心菜", "蔬菜", 0.50, 0.10, 25, 1.3, 5.8, 0.1, 2.5, 18),
    "lettuce": f("lettuce", "生菜", "蔬菜", 0.42, 0.10, 15, 1.4, 2.9, 0.2, 1.3, 28),
    "celery": f("celery", "芹菜", "蔬菜", 0.52, 0.10, 16, 0.7, 3.0, 0.2, 1.6, 80),
    "garlic_chive": f("garlic_chive", "韭菜", "蔬菜", 0.45, 0.10, 30, 2.4, 4.6, 0.4, 2.4, 25),
    "green_bean": f("green_bean", "四季豆", "蔬菜", 0.58, 0.10, 31, 1.8, 7.0, 0.1, 3.4, 6),
    "snow_pea": f("snow_pea", "荷兰豆", "蔬菜", 0.56, 0.10, 42, 2.8, 7.6, 0.2, 2.6, 4),
    "bean_sprout": f("bean_sprout", "豆芽", "蔬菜", 0.55, 0.10, 30, 3.0, 5.9, 0.2, 1.8, 6),
    # Other vegetables
    "tomato": f("tomato", "番茄", "蔬菜", 0.60, 0.08, 18, 0.9, 3.9, 0.2, 1.2, 5),
    "cucumber": f("cucumber", "黄瓜", "蔬菜", 0.55, 0.08, 15, 0.7, 3.6, 0.1, 0.5, 2),
    "carrot": f("carrot", "胡萝卜", "蔬菜", 0.70, 0.08, 41, 0.9, 9.6, 0.2, 2.8, 69),
    "eggplant": f("eggplant", "茄子", "蔬菜", 0.58, 0.10, 25, 1.0, 5.9, 0.2, 3.0, 2),
    "winter_melon": f("winter_melon", "冬瓜", "蔬菜", 0.62, 0.08, 13, 0.4, 3.0, 0.2, 0.9, 2),
    "bitter_melon": f("bitter_melon", "苦瓜", "蔬菜", 0.58, 0.10, 17, 1.0, 3.7, 0.2, 2.8, 5),
    "bell_pepper": f("bell_pepper", "彩椒", "蔬菜", 0.50, 0.10, 31, 1.0, 6.0, 0.3, 2.1, 4),
    "onion": f("onion", "洋葱", "蔬菜", 0.62, 0.08, 40, 1.1, 9.3, 0.1, 1.7, 4),
    "mushroom": f("mushroom", "蘑菇", "菌菇", 0.55, 0.10, 22, 3.1, 3.3, 0.3, 1.0, 5),
    "shiitake": f("shiitake", "香菇", "菌菇", 0.45, 0.10, 34, 2.2, 6.8, 0.5, 2.5, 9),
    "enoki": f("enoki", "金针菇", "菌菇", 0.42, 0.10, 37, 2.7, 7.8, 0.3, 2.7, 3),
    "wood_ear": f("wood_ear", "木耳", "菌菇", 0.35, 0.10, 25, 1.5, 6.8, 0.2, 5.0, 9),
    "bamboo_shoot": f("bamboo_shoot", "笋", "蔬菜", 0.55, 0.10, 27, 2.6, 5.2, 0.3, 2.2, 4),
    # Fruits
    "apple": f("apple", "苹果", "水果", 0.60, 0.08, 52, 0.3, 13.8, 0.2, 2.4, 1),
    "banana": f("banana", "香蕉", "水果", 0.66, 0.08, 89, 1.1, 22.8, 0.3, 2.6, 1),
    "orange": f("orange", "橙子", "水果", 0.62, 0.08, 47, 0.9, 11.8, 0.1, 2.4, 0),
    "watermelon": f("watermelon", "西瓜", "水果", 0.58, 0.08, 30, 0.6, 7.6, 0.2, 0.4, 1),
    # Desserts and packaged snacks
    "cake": f("cake", "蛋糕", "甜点", 0.42, 0.12, 348, 5.2, 50.6, 14.0, 1.0, 300),
    "sponge_cake": f("sponge_cake", "海绵蛋糕", "甜点", 0.35, 0.10, 320, 6.0, 55.0, 9.0, 0.8, 220),
    "cake_roll": f("cake_roll", "蛋糕卷", "甜点", 0.45, 0.12, 360, 6.0, 48.0, 16.0, 0.8, 260),
    "pork_floss_pastry": f("pork_floss_pastry", "肉松糕点", "甜点", 0.48, 0.12, 370, 9.0, 46.0, 17.0, 1.0, 420),
    "cream_cake": f("cream_cake", "奶油蛋糕", "甜点", 0.48, 0.14, 380, 4.5, 42.0, 22.0, 0.6, 240),
    "egg_tart": f("egg_tart", "蛋挞", "甜点", 0.55, 0.12, 375, 6.4, 37.0, 22.0, 0.5, 230),
    "bread": f("bread", "面包", "甜点", 0.32, 0.10, 265, 8.8, 49.0, 3.2, 2.7, 490),
    "sweet_bread": f("sweet_bread", "甜面包", "甜点", 0.35, 0.11, 330, 7.5, 55.0, 9.0, 1.6, 330),
    "biscuit": f("biscuit", "饼干", "零食", 0.50, 0.12, 435, 7.0, 70.0, 14.0, 2.5, 500),
    "cheese_cracker": f("cheese_cracker", "芝士饼干", "零食", 0.55, 0.12, 480, 8.0, 62.0, 22.0, 2.0, 700),
    "oreo_cookie": f("oreo_cookie", "夹心饼干", "零食", 0.58, 0.13, 480, 5.0, 70.0, 20.0, 2.0, 450),
    "cookie": f("cookie", "曲奇", "零食", 0.52, 0.12, 500, 6.0, 64.0, 25.0, 2.0, 420),
    "cracker": f("cracker", "苏打饼干", "零食", 0.45, 0.11, 430, 8.0, 72.0, 11.0, 2.4, 850),
    "wafer": f("wafer", "威化饼干", "零食", 0.32, 0.10, 520, 6.5, 62.0, 28.0, 1.8, 260),
    "chips": f("chips", "薯片", "零食", 0.18, 0.07, 540, 6.0, 52.0, 34.0, 4.0, 520),
    "chocolate": f("chocolate", "巧克力", "零食", 1.05, 0.10, 546, 4.9, 61.0, 31.0, 7.0, 24),
    "candy": f("candy", "糖果", "零食", 1.20, 0.12, 390, 0.0, 98.0, 0.0, 0.0, 20),
    "packaged_snack": f("packaged_snack", "包装零食", "零食", 0.42, 0.18, 470, 6.0, 66.0, 20.0, 2.0, 480),
    # Common mixed dishes
    "tomato_egg": f("tomato_egg", "番茄炒蛋", "混合菜", 0.78, 0.14, 98, 6.2, 4.2, 6.5, 0.8, 220),
    "mapo_tofu": f("mapo_tofu", "麻婆豆腐", "混合菜", 0.88, 0.16, 128, 8.0, 5.0, 8.5, 1.2, 420),
    "stir_fried_greens": f("stir_fried_greens", "炒青菜", "混合菜", 0.62, 0.14, 55, 2.2, 5.0, 3.2, 2.0, 260),
    "fried_rice": f("fried_rice", "炒饭", "混合菜", 0.78, 0.15, 188, 5.5, 28.0, 6.0, 1.2, 420),
    # Drinks
    "wine": f("wine", "红酒", "饮品", 0.99, 0.02, 85, 0.1, 2.6, 0.0, 0.0, 4),
    "milkshake": f("milkshake", "奶昔", "饮品", 1.05, 0.04, 120, 3.5, 20.0, 3.0, 0.0, 35),
    "coffee": f("coffee", "咖啡", "饮品", 0.99, 0.01, 2, 0.3, 0.0, 0.0, 0.0, 1),
    "juice": f("juice", "果汁", "饮品", 1.02, 0.02, 45, 0.7, 10.0, 0.2, 0.2, 2),
    "tea": f("tea", "茶", "饮品", 0.99, 0.01, 1, 0.0, 0.2, 0.0, 0.0, 1),
    # Condiments and sea vegetables
    "sauce": f("sauce", "酱汁", "调味品", 1.10, 0.08, 150, 5.0, 20.0, 5.0, 1.5, 1200),
    "kelp": f("kelp", "海带", "蔬菜", 0.55, 0.10, 43, 1.7, 9.1, 0.6, 2.5, 230),
    "seaweed": f("seaweed", "紫菜", "蔬菜", 0.25, 0.08, 35, 5.8, 5.1, 0.3, 3.0, 620),
    "ginger": f("ginger", "姜", "配料", 0.75, 0.08, 80, 1.8, 17.8, 0.8, 2.0, 13),
    "mixed_ingredients": f("mixed_ingredients", "混合配料", "混合菜", 0.70, 0.15, 100, 3.0, 12.0, 4.0, 1.5, 180),
    "unknown_food": f("unknown_food", "未知食物", "待确认", 0.70, 0.18, 120, 6.0, 15.0, 3.5, 1.5, 30),
}


def profile_for_key(key: str) -> FoodProfile:
    return FOOD_PROFILES.get(key, FOOD_PROFILES["unknown_food"])


def all_profiles() -> list[dict[str, object]]:
    return [asdict(profile) for profile in FOOD_PROFILES.values()]


def cooking_method_for_key(key: str) -> CookingAdjustment:
    return COOKING_METHODS.get(key, COOKING_METHODS["unknown"])


def nutrition_for_weight(profile: FoodProfile, weight_g: float, cooking_method: str = "unknown") -> Nutrition:
    factor = max(weight_g, 0) / 100
    adjustment = cooking_method_for_key(cooking_method)
    return Nutrition(
        calories_kcal=round((profile.calories_kcal_per_100g + adjustment.calories_delta_per_100g) * factor, 1),
        protein_g=round(profile.protein_g_per_100g * factor, 1),
        carbs_g=round((profile.carbs_g_per_100g + adjustment.carbs_delta_per_100g) * factor, 1),
        fat_g=round((profile.fat_g_per_100g + adjustment.fat_delta_per_100g) * factor, 1),
        fiber_g=round(profile.fiber_g_per_100g * factor, 1),
        sodium_mg=round((profile.sodium_mg_per_100g + adjustment.sodium_delta_per_100g) * factor, 1),
    )
