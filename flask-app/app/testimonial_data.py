"""首页 Testimonials 轮播查询"""

from app import db


def get_carousel_testimonials():
    """返回首页轮播用的全部 approved 评价（按后台拖拽排序）。"""
    from app.models import Testimonial

    try:
        return (
            Testimonial.query.filter_by(status="approved")
            .order_by(Testimonial.sort_order.asc(), Testimonial.id.asc())
            .all()
        )
    except Exception:
        return []


def assign_carousel_sort_order(testimonial):
    """将评价排到轮播末尾（approve 或后台新建 approved 时调用）。"""
    from app.models import Testimonial

    max_order = (
        db.session.query(db.func.max(Testimonial.sort_order))
        .filter(Testimonial.status == "approved")
        .scalar()
    )
    testimonial.sort_order = (max_order or 0) + 1


def next_testimonial_sort_order():
    """新条目默认排在全体最后。"""
    from app.models import Testimonial

    max_order = db.session.query(db.func.max(Testimonial.sort_order)).scalar()
    return (max_order or 0) + 1
