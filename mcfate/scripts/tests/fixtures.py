"""测试用固定数据（全部为构造数据，不含任何真实账号、令牌或门店信息）。"""

from __future__ import annotations

MENU_RAW = {
    "success": True,
    "code": 200,
    "message": "请求成功",
    "data": {
        "categories": [
            {"name": "人气热卖", "meals": [{"code": "1100", "tags": ["爆款"]}]},
            {
                "name": "巨无霸\n牛鱼肉堡",
                "meals": [
                    {"code": "1100", "tags": ["单品", "100%纯牛肉"]},
                    {"code": "4648", "tags": ["单品", "100%纯牛肉"]},
                ],
            },
            {"name": "炸鸡", "meals": [{"code": "1700", "tags": ["单品", "人气"]}]},
            {"name": "饮品", "meals": [{"code": "9900008751", "tags": ["冷饮"]}]},
            {"name": "麦咖啡™", "meals": [{"code": "507411", "tags": ["限定特惠"]}]},
            {"name": "小食甜品\n/其他", "meals": [{"code": "4810", "tags": ["小食"]}]},
            {"name": "BFF", "meals": [{"code": "9900015730", "tags": ["小食拼盘"]}]},
        ],
        "meals": {
            "1100": {"name": "巨无霸", "currentPrice": "26.5", "originalPrice": "26.5", "canWithOrder": False},
            "4648": {"name": "不素之霸双层牛堡", "currentPrice": "26.5", "originalPrice": "26.5"},
            "1700": {"name": "麦辣鸡翅", "currentPrice": "14.5", "originalPrice": "14.5"},
            "9900008751": {"name": "可乐", "currentPrice": "9.5", "originalPrice": "9.5"},
            "507411": {
                "name": "麦咖啡™美式",
                "currentPrice": "11.9",
                "originalPrice": "19",
                "discountType": "促销优惠",
            },
            "4810": {"name": "薯条", "currentPrice": "14.5", "originalPrice": "14.5"},
            "521900": {"name": "咸蛋黄鸡腿蛋月堡", "currentPrice": "25", "originalPrice": "25"},
            "9900015730": {"name": "BFF四宫格小食盘", "currentPrice": "40.3", "originalPrice": "53.5"},
        },
    },
}

COUPONS_RAW = {
    "success": True,
    "code": 200,
    "data": [
        {
            "title": "满30减6元券",
            "couponId": "C1",
            "couponCode": "CODE1",
            "tradeDateTime": "2026-10-31",
            "products": [{"productName": "巨无霸", "productCode": "1100"}],
            "threshold": "30",
        },
        {
            "title": "巨无霸立减3元",
            "couponId": "C2",
            "couponCode": "CODE2",
            "tradeDateTime": "2026-10-31",
            "products": [{"productName": "巨无霸", "productCode": "1100"}],
        },
        {
            "title": "麦辣鸡翅券",
            "couponId": "C3",
            "couponCode": "CODE3",
            "products": [{"productName": "麦辣鸡翅", "productCode": "1700"}],
            "threshold": "20",
        },
    ],
}

QUOTE_OK = {
    "success": True,
    "code": 200,
    "data": {
        "productOriginalPrice": 2650,
        "productPrice": 2650,
        "originalPrice": 2650,
        "discount": 0,
        "price": 2650,
        "productList": [
            {"productCode": "1100", "productName": "巨无霸", "quantity": 1, "originalSubtotal": 2650, "subtotal": 2650}
        ],
        "takeWayList": [{"code": "eat-in", "title": "堂食", "subtitle": "店内用餐"}],
    },
}

QUOTE_FAIL = {"success": False, "code": 500, "message": "门店繁忙，请稍后重试"}

QUOTE_WITH_COUPON = {
    "success": True,
    "code": 200,
    "data": {
        "originalPrice": 2650,
        "discount": 300,
        "price": 2350,
        "productList": [
            {"productCode": "1100", "productName": "巨无霸", "quantity": 1, "subtotal": 2350}
        ],
        "takeWayList": [{"code": "eat-in", "title": "堂食"}],
    },
}
