"""
Copilot Analytical Reasoner for Thu Hà AI Analytics Studio
Xử lý ngôn ngữ tự nhiên tiếng Việt chuyên sâu cho phân tích dữ liệu kinh doanh / bán lẻ / P&L.
Đảm bảo 100% tính chính xác của số liệu, hiểu đúng ý định, trả lời trúng đích câu hỏi.
"""

import json
import re
import unicodedata
from typing import Dict, Any, List, Optional, Tuple


def norm(s: Any) -> str:
    """Chuẩn hóa chuỗi: chữ thường, bỏ dấu tiếng Việt, loại bỏ ký tự lạ."""
    s = unicodedata.normalize("NFD", str(s or "")).lower()
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w%&]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def acc(s: Any) -> str:
    """Chữ thường, GIỮ dấu tiếng Việt (để phân biệt 'lỗi' / 'lợi' / 'lời')."""
    s = unicodedata.normalize("NFC", str(s or "")).lower()
    s = re.sub(r"[^\w%&]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def kw_match(query: str, kw: str) -> bool:
    """
    Từ khóa có dấu -> so khớp trên văn bản có dấu (giữ dấu).
    Từ khóa không dấu -> so khớp trên bản bỏ dấu (có word boundary).
    """
    if not kw:
        return False
    is_ascii = all(ord(c) < 128 for c in kw)
    if is_ascii:
        k = norm(kw)
        return bool(k) and f" {k} " in f" {norm(query)} "
    k = acc(kw)
    return bool(k) and f" {k} " in f" {acc(query)} "


def has_any(query: str, keywords: List[str]) -> bool:
    return any(kw_match(query, kw) for kw in keywords)


def fmt_num(val: Any, unit: str = "") -> str:
    """Định dạng số theo chuẩn tiếng Việt, tự động rút gọn triệu đ / tỷ đ."""
    if val is None or val == "":
        return "—"
    try:
        v = float(val)
    except (ValueError, TypeError):
        return str(val)

    if unit == "%":
        return f"{v:.1f}%"
    if unit == "đ":
        if abs(v) >= 1_000_000_000:
            return f"{v / 1_000_000_000:.2f} tỷ đ"
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f} triệu đ"
        if abs(v) >= 1_000:
            return f"{v / 1_000:.0f} nghìn đ"
        return f"{v:,.0f} đ".replace(",", ".")
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v.is_integer():
        return f"{int(v):,}".replace(",", ".") + (f" {unit}" if unit else "")
    return f"{v:.1f}".replace(".", ",") + (f" {unit}" if unit else "")


# ----------------------------------------------------------------------------
# Từ điển ý định
# ----------------------------------------------------------------------------
DIMENSIONS = {
    "product": {
        "label": "Sản phẩm", "key": "product_breakdown", "field": "product_id",
        "kw": ["sản phẩm", "san pham", "mặt hàng", "mat hang", "sku", "product", "hàng hóa", "hang hoa", "combo", "item", "sp"]
    },
    "channel": {
        "label": "Kênh bán", "key": "channel_breakdown", "field": "channel",
        "kw": ["kênh", "kenh", "channel", "nền tảng", "nen tang", "sàn tmđt", "san tmdt", "sàn thương mại", "san thuong mai", "website", "shopee", "lazada", "tiktok", "cửa hàng", "cua hang", "store", "offline", "online"]
    },
    "region": {
        "label": "Khu vực", "key": "region_breakdown", "field": "region",
        "kw": ["khu vực", "khu vuc", "vùng", "miền", "mien", "region", "tỉnh", "thành phố", "địa bàn", "chi nhánh"]
    },
    "time": {
        "label": "Thời gian", "key": "timeline_breakdown", "field": "date",
        "kw": ["tháng", "thang", "thời gian", "theo ngày", "ngày", "tuần", "quý", "năm", "xu hướng", "xu huong", "trend", "giai đoạn", "mùa", "time", "month"]
    },
    "category": {
        "label": "Danh mục", "key": "category_breakdown", "field": "category",
        "kw": ["danh mục", "ngành hàng", "category", "nhóm hàng", "loại hàng"]
    },
    "campaign": {
        "label": "Chiến dịch / Nhóm P&L", "key": "pnl_table", "field": "campaign_name",
        "kw": ["chiến dịch", "chien dich", "campaign", "chương trình", "khuyến mãi", "p&l", "pnl"]
    },
}

METRICS = {
    "net_revenue": {
        "label": "Doanh thu thuần", "unit": "đ",
        "kw": ["doanh thu", "doanh số", "doanh so", "revenue", "bán được", "ban duoc", "thu về", "sales", "tiền bán", "quy mô"]
    },
    "gross_profit": {
        "label": "Lợi nhuận gộp", "unit": "đ",
        "kw": ["lợi nhuận gộp", "loi nhuan gop", "lợi nhuận", "loi nhuan", "lãi", "lai", "profit", "lời", "kiếm được"]
    },
    "contribution_margin": {
        "label": "Lợi nhuận đóng góp (CM)", "unit": "đ",
        "kw": ["lợi nhuận đóng góp", "loi nhuan dong gop", "biên đóng góp", "bien dong gop", "contribution margin", "cm"]
    },
    "gross_margin_pct": {
        "label": "Biên lợi nhuận gộp", "unit": "%",
        "kw": ["biên lợi nhuận", "biên", "bien", "margin", "tỷ suất lợi nhuận", "ty suat loi nhuan", "hiệu quả sinh lời"]
    },
    "cogs": {
        "label": "Giá vốn (COGS)", "unit": "đ",
        "kw": ["giá vốn", "gia von", "cogs", "chi phí vốn", "chi phi von", "chi phí", "chi phi", "cost", "tốn"]
    },
    "orders_count": {
        "label": "Số đơn hàng", "unit": "đơn",
        "kw": ["số đơn", "so don", "đơn hàng", "don hang", "orders", "lượt mua", "số lượng đơn"]
    },
    "quantity_sold": {
        "label": "Số lượng bán", "unit": "SP",
        "kw": ["số lượng bán", "số lượng", "so luong", "sản lượng", "quantity", "bán ra", "số sản phẩm", "bán chạy", "ban chay"]
    },
    "return_amount": {
        "label": "Giá trị hoàn / trả hàng", "unit": "đ",
        "kw": ["tiền hoàn", "giá trị hoàn", "hoàn hàng", "trả hàng", "tra hang", "return", "đổi trả", "hủy"]
    },
    "return_rate_pct": {
        "label": "Tỷ lệ hoàn hàng", "unit": "%",
        "kw": ["tỷ lệ hoàn", "ty le hoan", "return rate", "tỉ lệ hoàn"]
    },
    "discount_amount": {
        "label": "Chiết khấu / Giảm giá", "unit": "đ",
        "kw": ["chiết khấu", "chiet khau", "giảm giá", "giam gia", "voucher", "discount", "khuyến mại"]
    },
    "aov": {
        "label": "Giá trị đơn trung bình (AOV)", "unit": "đ",
        "kw": ["aov", "giá trị trung bình", "trung bình mỗi đơn", "giá trị đơn", "basket"]
    },
    "revenue_share_pct": {
        "label": "Tỷ trọng doanh thu", "unit": "%",
        "kw": ["tỷ trọng", "ty trong", "chiếm bao nhiêu", "chiếm", "cơ cấu", "co cau", "đóng góp"]
    },
}

QTYPES = [
    ("greeting", ["xin chào", "chào bạn", "hello", "hi", "chao", "alo"]),
    ("help", ["bạn làm được gì", "giúp gì", "hướng dẫn", "cách dùng", "bạn là ai", "có thể hỏi gì"]),
    ("data_quality", ["lỗi làm sạch", "lỗi dữ liệu", "loi lam sach", "loi du lieu", "lỗi", "ngoại lệ", "ngoai le", "làm sạch", "lam sach", "thiếu dữ liệu", "trùng lặp", "trung lap", "bất thường", "chất lượng dữ liệu", "exception", "missing data", "duplicate"]),
    ("why", ["tại sao", "tai sao", "vì sao", "vi sao", "nguyên nhân", "nguyen nhan", "lý do", "ly do", "do đâu", "why"]),
    ("recommend", ["đề xuất", "de xuat", "nên làm gì", "nen lam", "giải pháp", "giai phap", "làm sao", "làm thế nào", "cải thiện", "cai thien", "tối ưu", "toi uu", "khuyến nghị", "chiến lược", "kế hoạch"]),
    ("compare", ["so sánh", "so sanh", "so với", "so voi", "khác nhau", "chênh lệch", "chenh lech", "hơn hay", "vs", "versus"]),
    ("trend", ["xu hướng", "xu huong", "tăng trưởng", "tang truong", "tăng hay giảm", "biến động", "bien dong", "diễn biến", "theo thời gian", "qua các tháng", "trend", "tăng", "giảm"]),
    ("bottom", ["thấp nhất", "thap nhat", "kém nhất", "kem nhat", "tệ nhất", "te nhat", "ít nhất", "it nhat", "yếu nhất", "lỗ", "chậm nhất", "nhỏ nhất", "thua", "tệ", "kém"]),
    ("top", ["cao nhất", "cao nhat", "nhiều nhất", "nhieu nhat", "tốt nhất", "tot nhat", "lớn nhất", "lon nhat", "dẫn đầu", "dan dau", "top", "bán chạy nhất", "ban chay nhat", "bán chạy", "ban chay", "hiệu quả nhất", "mạnh nhất", "best", "đứng đầu", "chủ lực"]),
    ("share", ["tỷ trọng", "ty trong", "chiếm bao nhiêu", "cơ cấu", "co cau", "phần trăm", "bao nhiêu %"]),
    ("total", ["tổng", "tong", "bao nhiêu", "bao nhieu", "là bao nhiêu", "total", "tất cả", "tổng cộng"]),
    ("list", ["liệt kê", "liet ke", "danh sách", "danh sach", "những", "các", "chi tiết", "chi tiet", "từng", "list"]),
    ("overview", ["tổng quan", "tong quan", "tóm tắt", "tom tat", "tình hình", "tinh hinh", "đánh giá chung", "báo cáo", "nhận xét", "overview", "summary", "thế nào", "ra sao"]),
]


class CopilotReasoner:
    def __init__(self, summary: Dict[str, Any]):
        self.s = summary or {}
        self.fin = self.s.get("financial_kpis") or self.s.get("summary_kpis") or {}
        self.records = self.s.get("cleaned_orders_table") or []
        self.meta = self.s.get("dataset_meta") or {}
        self.tables = self._build_tables()

    # ------------------------------------------------------------------
    # Chuẩn bị bảng số liệu theo từng chiều
    # ------------------------------------------------------------------
    def _merge_rows(self, rows: List[Dict], field: str) -> List[Dict]:
        merged: Dict[str, Dict] = {}
        order: List[str] = []
        for r in rows or []:
            raw_val = r.get(field) or r.get("product_name") or r.get("name") or r.get("sku") or r.get("campaign_name") or r.get("period") or r.get("label") or "Khác"
            label = re.sub(r"\s+", " ", str(raw_val)).strip()
            k = norm(label)
            if k not in merged:
                merged[k] = {"label": label}
                order.append(k)
            m = merged[k]
            # Copy or map quantity if present
            if "quantity" in r and "quantity_sold" not in r:
                r_item = dict(r)
                r_item["quantity_sold"] = r["quantity"]
            else:
                r_item = r
            for mk, mv in r_item.items():
                if isinstance(mv, (int, float)) and not isinstance(mv, bool):
                    if mk.endswith("_pct") or mk in ("aov",):
                        continue
                    m[mk] = m.get(mk, 0) + mv
        out = [merged[k] for k in order]
        tot_rev = sum(x.get("net_revenue", x.get("gross_revenue", 0)) or 0 for x in out) or 0
        for x in out:
            rev = x.get("net_revenue", x.get("gross_revenue", 0)) or 0
            if "net_revenue" not in x and "gross_revenue" in x:
                x["net_revenue"] = x["gross_revenue"]
            if "gross_profit" not in x and "cogs" in x and rev:
                x["gross_profit"] = rev - x["cogs"]
            if rev:
                if "gross_profit" in x:
                    x["gross_margin_pct"] = round(x["gross_profit"] / rev * 100, 1)
                if "return_amount" in x:
                    gross = x.get("gross_revenue", rev) or rev
                    x["return_rate_pct"] = round(x["return_amount"] / gross * 100, 1) if gross else 0
                if x.get("orders_count"):
                    x["aov"] = round(rev / x["orders_count"], 0)
                if tot_rev:
                    x["revenue_share_pct"] = round(rev / tot_rev * 100, 1)
        return out

    def _build_tables(self) -> Dict[str, Dict]:
        tables = {}
        for dim, cfg in DIMENSIONS.items():
            rows = self.s.get(cfg["key"]) or []
            if rows:
                tables[dim] = {"label": cfg["label"], "rows": self._merge_rows(rows, cfg["field"])}
        orig_cols = self.meta.get("original_columns") or []
        if self.records and orig_cols:
            profiling = {p.get("column_name"): p for p in (self.s.get("column_profiling") or [])}
            num_cols = [c for c in orig_cols if str((profiling.get(c) or {}).get("data_type", "")).startswith("Số")]
            cat_cols = [c for c in orig_cols if c not in num_cols]
            self.num_cols = num_cols
            for c in cat_cols:
                vals = {str(r.get(c)).strip() for r in self.records if r.get(c) not in (None, "")}
                if 1 < len(vals) <= 40:
                    tables[f"col::{c}"] = {"label": c, "rows": None, "column": c}
        else:
            self.num_cols = []
        return tables

    def _group_by_column(self, col: str) -> List[Dict]:
        groups: Dict[str, Dict] = {}
        for r in self.records:
            label = re.sub(r"\s+", " ", str(r.get(col) if r.get(col) not in (None, "") else "Khác").strip())
            k = norm(label)
            g = groups.setdefault(k, {"label": label, "records_count": 0})
            g["records_count"] += 1
            for num_c in getattr(self, "num_cols", []):
                val = r.get(num_c)
                if val is not None and val != "":
                    try:
                        clean_v = float(str(val).replace(",", ".").replace("%", "").strip())
                        low = norm(num_c)
                        if any(w in low for w in ["doanh thu", "revenue", "tien", "thanh tien"]):
                            target_k = "net_revenue"
                        elif any(w in low for w in ["so luong", "quantity", "so don"]):
                            target_k = "orders_count"
                        elif any(w in low for w in ["gia von", "cogs", "chi phi"]):
                            target_k = "cogs"
                        elif any(w in low for w in ["loi nhuan", "profit", "lai"]):
                            target_k = "gross_profit"
                        else:
                            target_k = num_c
                        g[target_k] = g.get(target_k, 0) + clean_v
                    except (ValueError, TypeError):
                        pass
        rows = list(groups.values())
        for g in rows:
            if g.get("net_revenue") and "cogs" in g:
                g["gross_profit"] = g["net_revenue"] - g["cogs"]
                g["gross_margin_pct"] = round(g["gross_profit"] / g["net_revenue"] * 100, 1)
        tot = sum(g.get("net_revenue", 0) for g in rows)
        if tot:
            for g in rows:
                g["revenue_share_pct"] = round(g.get("net_revenue", 0) / tot * 100, 1)
        return rows

    def get_rows(self, dim: str) -> List[Dict]:
        t = self.tables.get(dim)
        if not t:
            return []
        if t.get("rows") is None:
            t["rows"] = self._group_by_column(t["column"])
        return t["rows"]

    # ------------------------------------------------------------------
    # BƯỚC 1: PHÂN TÍCH Ý ĐỊNH
    # ------------------------------------------------------------------
    def analyze_intent(self, query: str) -> Dict[str, Any]:
        intent: Dict[str, Any] = {"query": query, "dimension": None, "metric": None,
                                  "qtypes": [], "entities": [], "top_n": None}

        # Kiểm tra câu hỏi tài chính vs lỗi dữ liệu
        is_profit_or_fin = has_any(query, ["lợi nhuận", "loi nhuan", "lãi", "lai", "lời", "doanh thu", "chi phí", "giá vốn", "tiền"])

        for qt, kws in QTYPES:
            if qt == "data_quality" and is_profit_or_fin:
                continue
            if has_any(query, kws):
                intent["qtypes"].append(qt)

        # "top N"
        m = re.search(r"\btop\s*(\d+)\b|\b(\d+)\s*(kenh|san pham|khu vuc|thang)", norm(query))
        if m:
            intent["top_n"] = int(m.group(1) or m.group(2))

        # Chỉ số: chọn từ khóa khớp dài nhất
        best_metric, best_len = None, 0
        for mk, cfg in METRICS.items():
            for kw in cfg["kw"]:
                if kw_match(query, kw) and len(kw) > best_len:
                    best_metric, best_len = mk, len(kw)
        intent["metric"] = best_metric

        # Đối tượng cụ thể được nhắc tới (VD: "Website", "Miền Bắc", "Combo A")
        for dim in list(self.tables.keys()):
            for row in self.get_rows(dim):
                lab = str(row.get("label", "")).strip()
                if len(lab) >= 3 and kw_match(query, lab):
                    intent["entities"].append({"dimension": dim, "label": row.get("label")})

        # Chiều phân tích: Ưu tiên theo độ dài từ khóa khớp
        dim_found = None
        dim_candidates = []
        for dim, cfg in DIMENSIONS.items():
            if dim in self.tables:
                for kw in cfg["kw"]:
                    if kw_match(query, kw):
                        dim_candidates.append((len(kw), dim))
        if dim_candidates:
            dim_candidates.sort(key=lambda x: x[0], reverse=True)
            # Nếu có từ khóa sản phẩm rõ ràng -> ưu tiên product
            has_prod = has_any(query, ["sản phẩm", "san pham", "mặt hàng", "mat hang", "sku", "product"])
            if has_prod and "product" in self.tables:
                dim_found = "product"
            else:
                dim_found = dim_candidates[0][1]

        if not dim_found:
            for dim, t in self.tables.items():
                if dim.startswith("col::") and t["label"] and kw_match(query, t["label"]):
                    dim_found = dim
                    break
        if not dim_found and intent["entities"]:
            dim_found = intent["entities"][0]["dimension"]
        intent["dimension"] = dim_found

        # Suy luận bổ sung
        if "trend" in intent["qtypes"] and not intent["dimension"] and "time" in self.tables:
            intent["dimension"] = "time"
        if intent["metric"] == "revenue_share_pct" and "share" not in intent["qtypes"]:
            intent["qtypes"].append("share")
        if len(intent["entities"]) >= 2 and "compare" not in intent["qtypes"]:
            intent["qtypes"].append("compare")
        if not intent["qtypes"]:
            intent["qtypes"] = ["overview"] if not (intent["dimension"] or intent["metric"] or intent["entities"]) else ["list"]
        return intent

    def describe_intent(self, intent: Dict[str, Any]) -> str:
        qt_names = {
            "top": "tìm nhóm cao nhất / dẫn đầu", "bottom": "tìm nhóm thấp nhất / yếu nhất",
            "compare": "so sánh giữa các nhóm", "trend": "xem xu hướng biến động", "why": "tìm nguyên nhân",
            "recommend": "xin đề xuất giải pháp", "share": "xem tỷ trọng / cơ cấu", "total": "hỏi con số tổng",
            "list": "liệt kê chi tiết", "data_quality": "hỏi về lỗi làm sạch / chất lượng dữ liệu",
            "overview": "đánh giá tổng quan"
        }
        parts = []
        if intent["qtypes"]:
            parts.append(", ".join(qt_names.get(q, q) for q in intent["qtypes"][:3]))
        if intent["entities"]:
            parts.append(f"cho đối tượng **{', '.join(e['label'] for e in intent['entities'])}**")
        if intent["metric"]:
            parts.append(f"về chỉ số **{METRICS.get(intent['metric'], {}).get('label', intent['metric'])}**")
        if intent["dimension"]:
            dim_label = self.tables.get(intent["dimension"], {}).get("label", intent["dimension"])
            parts.append(f"theo chiều **{dim_label}**")
        return "; ".join(parts) if parts else "phân tích dữ liệu tệp"

    # ------------------------------------------------------------------
    # BƯỚC 2: TRÍCH XUẤT NGỮ CẢNH GỌN (CHO GEMINI LLM)
    # ------------------------------------------------------------------
    def compact_context(self, intent: Optional[Dict[str, Any]] = None) -> str:
        ctx: Dict[str, Any] = {}
        if self.fin:
            ctx["financial_kpis"] = {k: v for k, v in self.fin.items() if isinstance(v, (int, float, str, bool))}

        dims_to_send = []
        if intent and intent.get("dimension") and intent["dimension"] not in dims_to_send:
            dims_to_send.append(intent["dimension"])
        for d in ("channel", "product", "time", "region", "campaign"):
            if d in self.tables and d not in dims_to_send:
                dims_to_send.append(d)

        for dim in dims_to_send[:3]:
            rows = self.get_rows(dim)
            if rows:
                lbl = self.tables[dim]["label"]
                ctx[f"bang_theo_{lbl}"] = [
                    {k: v for k, v in r.items() if isinstance(v, (int, float, str))}
                    for r in rows[:10]
                ]

        exc = self.s.get("exceptions_list") or []
        if exc:
            ctx["tom_tat_loi_du_lieu"] = [
                {"loai": e.get("type"), "mo_ta": e.get("description"), "huong_xu_ly": e.get("ai_solution")}
                for e in exc[:8]
            ]
        return json.dumps(ctx, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # BƯỚC 3: TRẢ LỜI CỤC BỘ THEO ĐÚNG Ý ĐỊNH
    # ------------------------------------------------------------------
    def _metric_for(self, intent: Dict, rows: List[Dict]) -> str:
        m = intent.get("metric")
        if m == "revenue_share_pct" or (not m and "share" in intent["qtypes"]):
            return "revenue_share_pct" if rows and "revenue_share_pct" in rows[0] else "net_revenue"
        if m and rows and any(m in r for r in rows):
            return m
        if m == "orders_count" and rows and "records_count" in rows[0]:
            return "records_count"
        if "top" in intent["qtypes"] and not m:
            if rows and "quantity_sold" in rows[0]:
                return "quantity_sold"
            if rows and "net_revenue" in rows[0]:
                return "net_revenue"
        return "net_revenue" if rows and "net_revenue" in rows[0] else (
            next((k for k in rows[0] if k != "label" and isinstance(rows[0][k], (int, float))), "net_revenue") if rows else "net_revenue"
        )

    def _metric_label_unit(self, mk: str) -> Tuple[str, str]:
        if mk in METRICS:
            return METRICS[mk]["label"], METRICS[mk]["unit"]
        if mk == "records_count":
            return "Số bản ghi", "dòng"
        low = norm(mk)
        unit = "đ" if any(w in low for w in ["vnd", "doanh thu", "chi phi", "loi nhuan", "gia"]) else ""
        return mk, unit

    def answer_locally(self, query: str, intent: Optional[Dict] = None) -> str:
        intent = intent or self.analyze_intent(query)
        qts = intent["qtypes"]
        understood = f"🎯 **Tôi hiểu bạn đang hỏi:** {self.describe_intent(intent)}.\n\n"

        if "greeting" in qts and len(query.split()) <= 4:
            return ("👋 Xin chào! Tôi là Cố vấn AI phân tích dữ liệu kinh doanh của bạn. Tôi đã đọc toàn bộ tệp số liệu.\n"
                    "Bạn có thể hỏi bất kỳ câu hỏi nào về tệp, ví dụ:\n"
                    "- *Kênh bán nào có doanh thu cao nhất?*\n- *Sản phẩm nào bán chạy nhất?*\n"
                    "- *Tổng lợi nhuận gộp và biên lợi nhuận là bao nhiêu?*\n- *Tỷ lệ hoàn hàng của các kênh thế nào?*\n"
                    "- *Tệp dữ liệu phát hiện những lỗi làm sạch nào?*\n- *Đề xuất giải pháp tối ưu chi phí và tăng trưởng.*")

        if not self.s or (not self.tables and not self.fin.get("total_net_revenue") and not self.records):
            return ("📁 Hiện chưa có dữ liệu nào được nạp vào hệ thống. Vui lòng tải tệp ở **Bước 1** rồi đặt câu hỏi — "
                    "tôi sẽ phân tích chuyên sâu và trả lời chính xác 100% theo số liệu thực tế trong tệp của bạn.")

        if "data_quality" in qts and not intent.get("metric"):
            return understood + self._answer_data_quality()
        if "why" in qts:
            return understood + self._answer_why(intent)
        if "recommend" in qts and not ({"top", "bottom", "compare", "trend"} & set(qts)):
            return understood + self._answer_recommend(intent)

        dim = intent.get("dimension")
        if dim:
            rows = self.get_rows(dim)
            if rows:
                return understood + self._answer_dimension(intent, dim, rows)

        if intent.get("metric") or "total" in qts:
            return understood + self._answer_total(intent)
        return understood + self._answer_overview()

    def _answer_dimension(self, intent: Dict, dim: str, rows: List[Dict]) -> str:
        qts = intent["qtypes"]
        dlabel = self.tables[dim]["label"]
        mk = self._metric_for(intent, rows)
        mlabel, unit = self._metric_label_unit(mk)
        valid = [r for r in rows if isinstance(r.get(mk), (int, float))]
        if not valid:
            return (f"⚠️ Tệp dữ liệu hiện chưa có cột chỉ số **{mlabel}** phân bổ theo **{dlabel}**. "
                    f"Các chỉ số sẵn sàng: "
                    + ", ".join(self._metric_label_unit(k)[0] for k in rows[0] if k != "label" and isinstance(rows[0][k], (int, float))[:5]))

        ents = [e["label"] for e in intent["entities"] if e["dimension"] == dim]
        sorted_desc = sorted(valid, key=lambda r: r[mk], reverse=True)
        total = sum(r[mk] for r in valid)
        n = intent.get("top_n") or 3
        lines: List[str] = []

        def row_line(r, i=None):
            extra = []
            if mk != "net_revenue" and "net_revenue" in r:
                extra.append(f"doanh thu {fmt_num(r['net_revenue'], 'đ')}")
            if mk != "revenue_share_pct" and "revenue_share_pct" in r:
                extra.append(f"chiếm {r['revenue_share_pct']}%")
            if mk != "gross_margin_pct" and "gross_margin_pct" in r:
                extra.append(f"biên {r['gross_margin_pct']}%")
            prefix = f"{i}. " if i else "- "
            return f"{prefix}**{r['label']}**: {fmt_num(r[mk], unit)}" + (f" ({', '.join(extra)})" if extra else "")

        if "compare" in qts and len(ents) >= 2:
            sel = [r for r in valid if r["label"] in ents]
            sel.sort(key=lambda r: r[mk], reverse=True)
            a, b = sel[0], sel[-1]
            diff = a[mk] - b[mk]
            ratio = (a[mk] / b[mk]) if b[mk] else None
            lines.append(f"✅ **Trả lời:** Về {mlabel}, **{a['label']}** cao hơn **{b['label']}** "
                         f"{fmt_num(diff, unit)}" + (f" (gấp {ratio:.1f} lần)." if ratio and unit != '%' else "."))
            lines.append("\n📊 **Số liệu so sánh chi tiết:**")
            lines += [row_line(r) for r in sel]
        elif ents and not ({"top", "bottom", "trend", "share", "compare"} & set(qts)):
            r = next((x for x in valid if x["label"] == ents[0]), None)
            if r:
                rank = sorted_desc.index(r) + 1
                lines.append(f"✅ **Trả lời:** **{r['label']}** đạt {mlabel} **{fmt_num(r[mk], unit)}**, "
                             f"xếp hạng **{rank}/{len(valid)}** trong danh mục {dlabel.lower()}.")
                lines.append("\n📊 **Chi tiết các chỉ số:**")
                lines += [f"- {self._metric_label_unit(k)[0]}: {fmt_num(v, self._metric_label_unit(k)[1])}"
                          for k, v in r.items() if k != "label" and isinstance(v, (int, float))][:8]
        elif "trend" in qts or dim == "time":
            seq = sorted(valid, key=lambda r: str(r["label"])) if dim == "time" else sorted_desc
            first, last = seq[0], seq[-1]
            chg = ((last[mk] - first[mk]) / first[mk] * 100) if first[mk] else 0
            direction = "TĂNG TRƯỞNG" if chg > 2 else ("SUY GIẢM" if chg < -2 else "DUY TRÌ ỔN ĐỊNH")
            peak = max(seq, key=lambda r: r[mk])
            low = min(seq, key=lambda r: r[mk])
            lines.append(f"✅ **Trả lời:** {mlabel} ghi nhận xu hướng **{direction}** — từ {fmt_num(first[mk], unit)} "
                         f"({first['label']}) lên {fmt_num(last[mk], unit)} ({last['label']}), biến động **{chg:+.1f}%**.")
            lines.append(f"- Điểm cao nhất: **{peak['label']}** ({fmt_num(peak[mk], unit)}); Thấp nhất: **{low['label']}** ({fmt_num(low[mk], unit)}).")
            lines.append("\n📊 **Diễn biến theo mốc thời gian:**")
            for r in seq:
                lines.append(f"- **{r['label']}**: {fmt_num(r[mk], unit)}")
        elif "bottom" in qts and "top" not in qts:
            worst = sorted_desc[::-1][:n]
            lines.append(f"✅ **Trả lời:** {dlabel} có {mlabel} **thấp nhất** là **{worst[0]['label']}** với "
                         f"**{fmt_num(worst[0][mk], unit)}**" + (f" (chỉ chiếm {worst[0][mk] / total * 100:.1f}% quy mô)." if total else "."))
            lines.append(f"\n📊 **Danh sách {len(worst)} nhóm thấp nhất:**")
            lines += [row_line(r, i + 1) for i, r in enumerate(worst)]
            lines.append(f"\n💡 **Khuyến nghị AI:** Cần rà soát cơ cấu chi phí và giá bán của **{worst[0]['label']}**; "
                         f"nhân bản kinh nghiệm quản trị từ nhóm dẫn đầu **{sorted_desc[0]['label']}**.")
        elif "top" in qts:
            best = sorted_desc[:n]
            lines.append(f"✅ **Trả lời:** {dlabel} có {mlabel} **cao nhất** là **{best[0]['label']}** với "
                         f"**{fmt_num(best[0][mk], unit)}**" + (f" (chiếm {best[0][mk] / total * 100:.1f}% tổng quy mô)." if total else "."))
            lines.append(f"\n📊 **Top {len(best)} dẫn đầu:**")
            lines += [row_line(r, i + 1) for i, r in enumerate(best)]
            lines.append(f"\n💡 **Khuyến nghị AI:** Tiếp tục duy trì vị thế dẫn đầu của **{best[0]['label']}**, "
                         f"đồng thời đẩy mạnh chuyển giao mô hình sang các nhóm còn lại.")
        else:
            lines.append(f"✅ **Trả lời:** {mlabel} theo từng {dlabel.lower()} (sắp xếp theo quy mô):")
            lines += [row_line(r, i + 1) for i, r in enumerate(sorted_desc[:12])]
            if unit != "%" and total:
                lines.append(f"\n**Tổng cộng toàn bộ:** {fmt_num(total, unit)}")

        return "\n".join(lines)

    def _answer_total(self, intent: Dict) -> str:
        mk = intent.get("metric") or "net_revenue"
        label, unit = self._metric_label_unit(mk)

        # Truy xuất thông minh từ financial_kpis
        val = None
        if mk == "net_revenue":
            val = self.fin.get("total_net_revenue") or self.fin.get("net_revenue") or self.fin.get("total_gross_revenue")
        elif mk == "gross_profit":
            val = self.fin.get("total_gross_profit") or self.fin.get("gross_profit")
            if val is None:
                net = self.fin.get("total_net_revenue") or self.fin.get("net_revenue") or 0
                cogs = self.fin.get("total_cogs") or self.fin.get("cogs") or 0
                if net > 0 and cogs > 0:
                    val = net - cogs
        elif mk == "contribution_margin":
            val = self.fin.get("total_contribution_margin") or self.fin.get("total_cm") or self.fin.get("contribution_margin") or self.fin.get("cm")
        elif mk == "gross_margin_pct":
            val = self.fin.get("gross_margin_pct")
            if val is None:
                net = self.fin.get("total_net_revenue") or 0
                gp = self.fin.get("total_gross_profit") or 0
                if net > 0 and gp > 0:
                    val = round(gp / net * 100, 1)
        elif mk == "cogs":
            val = self.fin.get("total_cogs") or self.fin.get("cogs")
        elif mk == "orders_count":
            val = self.fin.get("total_orders") or self.fin.get("orders_count") or len(self.records)
        elif mk == "return_amount":
            val = self.fin.get("total_return_amount") or self.fin.get("total_returns") or self.fin.get("return_amount")
        elif mk == "return_rate_pct":
            val = self.fin.get("return_rate_pct")
            if val is None:
                ret = self.fin.get("total_return_amount") or self.fin.get("total_returns") or 0
                gross = self.fin.get("total_gross_revenue") or self.fin.get("total_net_revenue") or 0
                if gross > 0:
                    val = round(ret / gross * 100, 2)
        elif mk == "discount_amount":
            val = self.fin.get("total_discount_amount") or self.fin.get("total_discount") or self.fin.get("discount_amount")
        elif mk == "aov":
            val = self.fin.get("aov")
            if val is None:
                net = self.fin.get("total_net_revenue") or 0
                orders = self.fin.get("total_orders") or len(self.records) or 0
                if net > 0 and orders > 0:
                    val = round(net / orders, 0)
        elif mk == "quantity_sold":
            val = self.fin.get("total_quantity") or self.fin.get("quantity_sold")
            if val is None and self.records:
                try:
                    val = sum(float(r.get("quantity_sold") or r.get("quantity") or r.get("so_luong") or 0) for r in self.records if isinstance(r, dict))
                except Exception:
                    pass

        if val is None:
            return f"⚠️ Tệp dữ liệu hiện không có đủ thông tin để tính chỉ số **{label}**. Bạn có thể hỏi về doanh thu thuần, số lượng đơn hàng, hoặc các chỉ số P&L khác."

        out = [f"✅ **Trả lời:** {label} của toàn bộ tệp đạt **{fmt_num(val, unit)}**."]
        rev = self.fin.get("total_net_revenue") or self.fin.get("net_revenue")
        if rev and mk in ("gross_profit", "cogs", "contribution_margin", "discount_amount", "return_amount") and unit == "đ":
            out.append(f"- Tương đương **{val / rev * 100:.1f}%** doanh thu thuần ({fmt_num(rev, 'đ')}).")
        orders = self.fin.get("total_orders") or len(self.records)
        if orders and mk not in ("orders_count",):
            out.append(f"- Ghi nhận trên tổng quy mô **{fmt_num(orders)}** đơn hàng / bản ghi hợp lệ.")
        return "\n".join(out)

    def _answer_data_quality(self) -> str:
        exc = self.s.get("exceptions_list") or []
        if not exc:
            return "✅ **Trả lời:** Tệp dữ liệu sạch — hệ thống không phát hiện lỗi nào cần xử lý."
        groups: Dict[str, List] = {}
        for e in exc:
            groups.setdefault(e.get("type", "KHÁC"), []).append(e)
        out = [f"✅ **Trả lời:** Hệ thống quét và phát hiện **{len(groups)} nhóm lỗi** ({len(exc)} trường hợp bất thường) trong tệp:"]
        for i, (t, items) in enumerate(groups.items(), 1):
            e = items[0]
            out.append(f"{i}. **{e.get('description') or t}** ({len(items)} bản ghi)")
            if e.get("impact"):
                out.append(f"   - Ảnh hưởng: {e['impact']}")
            if e.get("ai_solution"):
                out.append(f"   - Hướng giải quyết AI: {e['ai_solution']}")
        out.append("\n👉 Bạn có thể rà soát và phê duyệt từng hướng xử lý tại **Bước 2 – Làm sạch & Phê duyệt**.")
        return "\n".join(out)

    def _answer_why(self, intent: Dict) -> str:
        out = ["✅ **Phân tích nguyên nhân cốt lõi từ số liệu tệp:**"]
        matrix = self.s.get("problem_solution_matrix") or []
        if matrix:
            for item in matrix[:3]:
                out.append(f"\n• **{item.get('title')}**")
                if item.get("evidence"):
                    out.append(f"  - Minh chứng số liệu: {item['evidence']}")
                if item.get("root_cause"):
                    out.append(f"  - Nguyên nhân gốc rễ: {item['root_cause']}")
        else:
            ret = self.fin.get("return_rate_pct") or 0
            cm_pct = self.fin.get("cm_pct") or 0
            if ret > 10:
                out.append(f"- Tỷ lệ hoàn hàng ở mức cao (**{ret:.1f}%**) gây xói mòn lợi nhuận và gia tăng chi phí logistics.")
            if cm_pct < 15:
                out.append(f"- Biên lợi nhuận đóng góp mỏng (**{cm_pct:.1f}%**) do tỷ lệ chiết khấu voucher sâu hoặc chi phí giá vốn cao.")
            if len(out) == 1:
                out.append("- Hiệu quả phụ thuộc vào sự chênh lệch quy mô giữa các kênh dẫn đầu và các kênh có chi phí cao.")
        return "\n".join(out)

    def _answer_recommend(self, intent: Dict, short: bool = False) -> str:
        recs = self.s.get("recommendations") or []
        out = ["💡 **Đề xuất hành động chiến lược từ AI Studio:**"]
        if recs:
            for i, r in enumerate(recs[:3 if short else 5], 1):
                name = r.get("campaign_name") or r.get("target") or "Chiến lược"
                dec = r.get("decision") or r.get("action") or "Tối ưu hóa"
                reason = r.get("primary_reason") or r.get("reason") or ""
                out.append(f"{i}. **{name}** → Quyết định: **{dec}**" + (f" ({reason})" if reason else ""))
        else:
            out.append("1. **Tập trung nguồn lực vào nhóm hiệu quả:** Tăng đầu tư cho kênh và sản phẩm có biên lợi nhuận đóng góp cao nhất.")
            out.append("2. **Cắt giảm lãng phí:** Siết chặt trần chiết khấu voucher và giảm tỷ lệ hoàn hủy ở các kênh yếu kém.")
            out.append("3. **Theo dõi nhịp biến động:** Đặt ngưỡng cảnh báo rủi ro khi biên lợi nhuận tụt xuống dưới 15%.")
        return "\n".join(out)

    def _answer_overview(self) -> str:
        rev = self.fin.get("total_net_revenue") or self.fin.get("net_revenue") or 0
        cm = self.fin.get("total_contribution_margin") or self.fin.get("total_cm") or 0
        orders = self.fin.get("total_orders") or len(self.records) or 0
        cm_pct = (cm / rev * 100) if rev else (self.fin.get("cm_pct") or 0)
        ret_rate = self.fin.get("return_rate_pct") or 0

        lines = [
            f"✅ **Tổng quan hiệu quả kinh doanh từ tệp dữ liệu:**",
            f"- **Doanh thu thuần:** {fmt_num(rev, 'đ')}",
            f"- **Lợi nhuận đóng góp (CM):** {fmt_num(cm, 'đ')} (Biên CM: **{cm_pct:.1f}%**)",
            f"- **Quy mô:** {fmt_num(orders)} đơn hàng / bản ghi",
            f"- **Tỷ lệ hoàn hàng:** {ret_rate:.1f}%"
        ]
        ch_rows = self.get_rows("channel")
        if ch_rows:
            top_ch = max(ch_rows, key=lambda r: r.get("net_revenue", 0))
            lines.append(f"- **Kênh bán chủ lực:** {top_ch['label']} ({fmt_num(top_ch.get('net_revenue', 0), 'đ')})")
        prod_rows = self.get_rows("product")
        if prod_rows:
            top_p = max(prod_rows, key=lambda r: r.get("quantity_sold", r.get("gross_revenue", 0)))
            lines.append(f"- **Sản phẩm dẫn đầu:** {top_p['label']}")
        lines.append("\n👉 Bạn có thể đặt câu hỏi chi tiết về từng kênh bán, sản phẩm, chi phí hoặc yêu cầu so sánh chuyên sâu.")
        return "\n".join(lines)
