"""Add 10 popular domestic cities with demo attractions.

Idempotent: cities missing from the database are inserted, existing slugs are
skipped. Ticket prices and opening hours are reference values that need manual
review before treating them as production data.

Run from the backend directory:
    .venv\\Scripts\\python.exe -B scripts\\add_popular_cities.py
"""

from sqlalchemy import select

from app.db import SessionLocal
from app.main import sync_media_catalog
from app.models import Attraction, City

# Each city: slug, name, aliases, description, season, budget, recommended_days
# and five attractions as (name, description, tags, opening_hours, ticket_price,
# duration_minutes, area). Prices are reference values for demo purposes.
CITY_DEFINITIONS = [
    {
        "slug": "guangzhou",
        "name": "广州",
        "aliases": ["广州市", "羊城"],
        "description": "广府美食、骑楼老街与珠江夜景交织的岭南都市，适合慢逛与寻味。",
        "season": "秋冬舒适，夏季湿热多雨",
        "budget": "¥400-800/天",
        "recommended_days": "2-4天",
        "attractions": [
            ("广州塔", "珠江新城地标，登塔可俯瞰广州全城与珠江夜景。", ["夜景", "休闲"], "09:30-22:30", 150, 120, "海珠区"),
            ("陈家祠", "岭南建筑与木雕、砖雕、灰塑精华所在的清代祠堂。", ["历史", "文化"], "09:00-17:30", 10, 120, "荔湾区"),
            ("沙面岛", "欧陆风情建筑群与江畔绿地，适合步行与拍照。", ["文化", "休闲"], "全天开放", 0, 120, "荔湾区"),
            ("白云山", "城市绿肺，登高可远眺广州城市全景。", ["自然", "休闲"], "06:00-22:00", 5, 180, "白云区"),
            ("越秀公园", "五羊石像与镇海楼所在的老牌城市公园。", ["历史", "自然", "休闲"], "06:00-22:00", 0, 120, "越秀区"),
        ],
    },
    {
        "slug": "changsha",
        "name": "长沙",
        "aliases": ["长沙市", "星城"],
        "description": "湘菜夜宵、千年学府与热闹街头组成充满烟火气的城市。",
        "season": "春秋舒适，夏季炎热",
        "budget": "¥300-600/天",
        "recommended_days": "2-3天",
        "attractions": [
            ("岳麓山", "登高俯瞰湘江，山脚有岳麓书院与爱晚亭。", ["自然", "历史", "文化"], "06:00-22:00", 0, 180, "岳麓区"),
            ("橘子洲", "湘江中央的洲岛，青年毛泽东雕像与城市天际线。", ["自然", "休闲", "夜景"], "全天开放", 0, 150, "岳麓区"),
            ("湖南博物院", "马王堆汉墓出土文物集中展示地。", ["历史", "文化"], "09:00-17:00（周一闭馆）", 0, 150, "开福区"),
            ("太平老街", "青石板老街里的长沙小吃与老字号。", ["美食", "文化"], "全天开放", 0, 120, "天心区"),
            ("天心阁", "长沙古城墙上的阁楼，可俯瞰老城烟火。", ["历史", "文化"], "08:00-18:00", 0, 90, "天心区"),
        ],
    },
    {
        "slug": "lhasa",
        "name": "拉萨",
        "aliases": ["拉萨市"],
        "description": "高原日光之城，寺院、转经道与雪山映衬的信仰与风景。",
        "season": "6-9月氧气充足，冬季晴朗少雨",
        "budget": "¥400-800/天",
        "recommended_days": "3-5天",
        "attractions": [
            ("布达拉宫", "世界文化遗产，依山而建的宫堡式建筑群。", ["历史", "文化"], "09:00-15:30（预约制）", 200, 180, "城关区"),
            ("大昭寺", "藏传佛教圣地，供奉释迦牟尼十二岁等身像。", ["历史", "文化"], "08:00-18:00", 85, 120, "城关区"),
            ("八廓街", "环绕大昭寺的转经道与特色商业街。", ["文化", "美食", "购物"], "全天开放", 0, 120, "城关区"),
            ("罗布林卡", "历代达赖喇嘛的夏宫园林，被称为拉萨的绿洲。", ["历史", "自然", "休闲"], "09:00-18:00", 60, 150, "城关区"),
            ("哲蚌寺", "规模宏大的格鲁派寺院，可俯瞰拉萨河谷。", ["历史", "文化"], "09:00-17:00", 60, 150, "城关区"),
        ],
    },
    {
        "slug": "yili",
        "name": "伊犁",
        "aliases": ["伊犁哈萨克自治州"],
        "description": "天山脚下的草原与河谷，哈萨克族风情与四季风光。",
        "season": "5-9月草原最佳，冬季雪景独特",
        "budget": "¥500-900/天",
        "recommended_days": "3-6天",
        "attractions": [
            ("那拉提草原", "空中草原与森林雪山，可体验哈萨克族游牧生活。", ["自然"], "08:00-20:00", 95, 240, "新源县"),
            ("喀拉峻草原", "天山高山草甸，五花草甸与人体草原起伏线条。", ["自然"], "08:00-20:00", 80, 240, "特克斯县"),
            ("喀赞其民俗旅游区", "伊宁老城蓝墙民居与维吾尔族民俗体验。", ["文化", "美食"], "全天开放", 0, 150, "伊宁市"),
            ("六星街", "多民族聚居的特色街巷与手工艺品小店。", ["文化", "美食"], "全天开放", 0, 120, "伊宁市"),
            ("果子沟大桥观景台", "跨越峡谷的高架桥，沿途雪山森林景观壮美。", ["自然"], "全天开放", 0, 90, "霍城县"),
        ],
    },
    {
        "slug": "wuhan",
        "name": "武汉",
        "aliases": ["武汉市", "江城"],
        "description": "两江交汇的江城，过早文化、博物馆与东湖风光。",
        "season": "春秋最佳，梅雨季节湿闷",
        "budget": "¥350-700/天",
        "recommended_days": "2-4天",
        "attractions": [
            ("黄鹤楼", "江南名楼，登楼可望长江大桥与两江汇流。", ["历史", "文化", "夜景"], "08:00-18:00", 70, 150, "武昌区"),
            ("东湖绿道", "环湖绿道串联湖光山色，骑行漫步皆宜。", ["自然", "休闲"], "全天开放", 0, 180, "武昌区"),
            ("湖北省博物馆", "曾侯乙编钟与越王勾践剑等馆藏重器。", ["历史", "文化"], "09:00-17:00（周一闭馆）", 0, 150, "武昌区"),
            ("户部巷", "汉味早点一条街，体验武汉过早文化。", ["美食"], "全天开放", 0, 90, "武昌区"),
            ("江汉路步行街", "百年商业老街与万国建筑博览。", ["购物", "美食", "文化"], "全天开放", 0, 120, "江汉区"),
        ],
    },
    {
        "slug": "chongqing",
        "name": "重庆",
        "aliases": ["重庆市", "山城"],
        "description": "8D魔幻山城，火锅、夜景与穿楼而过的轨道交通。",
        "season": "春秋舒适，夏季酷热",
        "budget": "¥350-700/天",
        "recommended_days": "2-4天",
        "attractions": [
            ("洪崖洞", "依山而建的吊脚楼夜景，嘉陵江畔的立体街市。", ["夜景", "美食", "文化"], "全天开放", 0, 150, "渝中区"),
            ("长江索道", "跨江缆车，从空中看山城江景。", ["休闲", "夜景"], "07:30-22:00", 20, 60, "渝中区"),
            ("磁器口古镇", "嘉陵江边的古镇，陈麻花与毛血旺的老字号。", ["美食", "历史", "文化"], "全天开放", 0, 120, "沙坪坝区"),
            ("南山一棵树观景台", "俯瞰渝中半岛夜景的经典观景台。", ["夜景", "休闲"], "09:00-22:30", 30, 90, "南岸区"),
            ("解放碑步行街", "重庆中心商圈与抗战纪念地标。", ["购物", "夜景"], "全天开放", 0, 120, "渝中区"),
        ],
    },
    {
        "slug": "hangzhou",
        "name": "杭州",
        "aliases": ["杭州市"],
        "description": "湖光山色与江南雅韵，西湖四季皆是画。",
        "season": "春秋最佳，梅雨季节湿闷",
        "budget": "¥400-800/天",
        "recommended_days": "2-4天",
        "attractions": [
            ("西湖", "环湖慢行、乘船或骑行，看断桥残雪与苏堤春晓。", ["自然", "休闲", "历史"], "全天开放", 0, 180, "西湖区"),
            ("灵隐寺", "千年古刹与飞来峰石刻造像。", ["历史", "文化"], "07:00-18:15", 75, 150, "西湖区"),
            ("西溪国家湿地公园", "城市湿地，可乘摇橹船穿行芦苇水道。", ["自然", "休闲"], "08:00-17:30", 80, 180, "西湖区"),
            ("雷峰塔", "登塔俯瞰西湖全貌，傍晚可看雷峰夕照。", ["历史", "文化", "夜景"], "08:00-20:00", 40, 90, "西湖区"),
            ("河坊街", "南宋御街旁的市井老街，杭帮小吃与手作。", ["美食", "文化", "购物"], "全天开放", 0, 120, "上城区"),
        ],
    },
    {
        "slug": "suzhou",
        "name": "苏州",
        "aliases": ["苏州市", "姑苏"],
        "description": "园林之城，粉墙黛瓦、小桥流水与精雅慢生活。",
        "season": "春秋最佳，夏季暑热冬季湿冷",
        "budget": "¥400-800/天",
        "recommended_days": "2-4天",
        "attractions": [
            ("拙政园", "苏州古典园林代表作，四季皆景。", ["历史", "自然", "文化"], "07:30-17:30", 70, 150, "姑苏区"),
            ("虎丘", "吴中第一名胜，云岩寺塔是苏州地标。", ["历史", "文化", "自然"], "07:30-17:30", 70, 150, "姑苏区"),
            ("平江路历史街区", "傍河老街，评弹声里的江南生活。", ["文化", "美食", "休闲"], "全天开放", 0, 120, "姑苏区"),
            ("苏州博物馆", "贝聿铭设计的园林式博物馆，馆藏与建筑皆美。", ["文化", "历史"], "09:00-17:00（周一闭馆）", 0, 120, "姑苏区"),
            ("周庄古镇", "水乡泽国，双桥与沈厅张厅的古韵。", ["历史", "文化", "美食"], "08:00-21:00", 100, 180, "昆山市"),
        ],
    },
    {
        "slug": "nanjing",
        "name": "南京",
        "aliases": ["南京市", "金陵"],
        "description": "六朝古都，梧桐大道、博物馆与城墙烟水。",
        "season": "春秋最佳，夏季炎热",
        "budget": "¥400-800/天",
        "recommended_days": "2-4天",
        "attractions": [
            ("中山陵", "依钟山而建的纪念建筑群，392级台阶庄严肃穆。", ["历史", "自然"], "08:30-17:00（周一闭馆）", 0, 150, "玄武区"),
            ("夫子庙秦淮河", "古秦淮夜景与夫子庙步行街的烟火气。", ["历史", "文化", "夜景", "美食"], "全天开放", 0, 150, "秦淮区"),
            ("玄武湖", "江南最大的城内公园，环湖看紫峰与明城墙。", ["自然", "休闲", "历史"], "06:00-22:00", 0, 150, "玄武区"),
            ("南京博物院", "馆藏丰富，一院六馆的国民级博物馆。", ["历史", "文化"], "09:00-17:00（周一闭馆）", 0, 180, "玄武区"),
            ("总统府", "见证近代历史的建筑群与园林。", ["历史", "文化"], "08:30-18:00（周一闭馆）", 35, 150, "玄武区"),
        ],
    },
    {
        "slug": "weihai",
        "name": "威海",
        "aliases": ["威海市"],
        "description": "山海相拥的海滨城市，渔港、海风与洁净海岸线。",
        "season": "5-10月海滨最佳，冬暖夏凉",
        "budget": "¥350-700/天",
        "recommended_days": "2-4天",
        "attractions": [
            ("刘公岛", "甲午战争纪念地，海岛森林与历史陈列馆。", ["历史", "自然"], "07:30-17:30", 138, 240, "环翠区"),
            ("成山头", "中国大陆海岸最东端，海天一色与秦皇东巡遗迹。", ["自然", "历史"], "08:00-17:00", 148, 180, "荣成市"),
            ("威海国际海水浴场", "沙质细软的海滨浴场，适合亲水休闲。", ["休闲", "自然"], "全天开放", 0, 120, "环翠区"),
            ("环翠楼公园", "城中制高点，可俯瞰威海湾与城市全景。", ["休闲", "自然"], "08:30-17:00", 0, 90, "环翠区"),
            ("华夏城", "大型生态文化景区，山水园林与仿古建筑。", ["自然", "文化"], "08:00-17:30", 98, 180, "环翠区"),
        ],
    },
]


def add_popular_cities() -> int:
    """Insert missing cities and their demo attractions. Returns number added."""
    db = SessionLocal()
    try:
        added = 0
        for definition in CITY_DEFINITIONS:
            if db.scalar(select(City).where(City.slug == definition["slug"])):
                print(f"跳过（已存在）: {definition['name']}")
                continue
            city = City(
                slug=definition["slug"],
                name=definition["name"],
                aliases=definition["aliases"],
                description=definition["description"],
                season=definition["season"],
                budget=definition["budget"],
                recommended_days=definition["recommended_days"],
                image_url="",
                support_level="full",
                planning_enabled=True,
                is_active=True,
            )
            db.add(city)
            db.flush()
            for name, description, tags, hours, price, duration, area in definition["attractions"]:
                db.add(Attraction(
                    city_id=city.id,
                    name=name,
                    description=description,
                    tags=tags,
                    opening_hours=hours,
                    ticket_price=price,
                    duration_minutes=duration,
                    area=area,
                    latitude=None,
                    longitude=None,
                    image_url="",
                ))
            print(f"已添加: {definition['name']}（{len(definition['attractions'])} 个景点，票价/开放时间为参考值需人工核验）")
            added += 1
        if added:
            db.flush()
            sync_media_catalog(db)
        db.commit()
        return added
    finally:
        db.close()


if __name__ == "__main__":
    count = add_popular_cities()
    print(f"本次新增城市: {count} 个。若无新增说明对应城市此前已存在。")
