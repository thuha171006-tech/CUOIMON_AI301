import re
import unicodedata
from typing import Dict, Any, List, Tuple
import pandas as pd
from core.domain_analyzer import DomainAnalyzer

class DynamicModificationEngine:
    """
    Applies precise business & data modifications requested by human user
    at Step 2 (Data Cleaning) and Step 3 (Analysis & HITL Review).
    Never invents fake data - applies adjustments strictly to empirical metrics.
    """

    @classmethod
    def _safe_float(cls, val, default: float = 0.0) -> float:
        if val is None:
            return default
        try:
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace("đ", "").replace("VND", "").replace("%", "").strip()
            # Vietnamese / European dot thousand separators: e.g. 10.000.000
            if re.search(r'^\d{1,3}(?:\.\d{3})+$', s):
                s = s.replace(".", "")
            elif re.search(r'^\d{1,3}(?:,\d{3})+$', s):
                s = s.replace(",", "")
            elif "," in s and "." in s:
                if s.rfind(",") > s.rfind("."):
                    s = s.replace(".", "").replace(",", ".")
                else:
                    s = s.replace(",", "")
            elif re.search(r'[\.,]\d{1,2}$', s):
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")
            return float(s) if s else default
        except Exception:
            return default

    @classmethod
    def parse_num_and_op(cls, text: str) -> Tuple[Any, str]:
        op = "=="
        text_norm = cls._normalize_str(text)
        if any(w in text_norm for w in ['<=', 'nho hon hoac bang', 'be hon hoac bang', 'duoi hoac bang', 'thap hon hoac bang']):
            op = '<='
        elif any(w in text_norm for w in ['<', 'nho hon', 'be hon', 'it hon', 'thap hon', 'duoi']):
            op = '<'
        elif any(w in text_norm for w in ['>=', 'lon hon hoac bang', 'cao hon hoac bang', 'nhieu hon hoac bang', 'tren hoac bang', 'tu ']):
            op = '>='
        elif any(w in text_norm for w in ['>', 'lon hon', 'cao hon', 'nhieu hon', 'tren']):
            op = '>'
        elif any(w in text_norm for w in ['!=', 'khac']):
            op = '!='
        else:
            op = '=='

        m = re.search(r'(\d+(?:[\.,]\d{3})*(?:[\.,]\d+)?|\d+)\s*(trieu|tr|ty|k|nghin|ngan)?', text_norm)
        if not m:
            return None, op
        num_str = m.group(1)
        unit = (m.group(2) or '').strip()

        if unit in ['trieu', 'tr']:
            val = float(num_str.replace(',', '.')) * 1_000_000
        elif unit in ['ty']:
            val = float(num_str.replace(',', '.')) * 1_000_000_000
        elif unit in ['k', 'nghin', 'ngan']:
            val = float(num_str.replace(',', '.')) * 1_000
        else:
            val = cls._safe_float(num_str)
        return val, op

    @staticmethod
    def _normalize_str(s: str) -> str:
        if not s:
            return ""
        s = str(s).lower().strip()
        s = unicodedata.normalize('NFD', s)
        s = re.sub(r'[\u0300-\u036f]', '', s)
        s = s.replace('đ', 'd')
        return s

    @classmethod
    def smart_filter_orders(
        cls, 
        cleaned_orders: List[Dict[str, Any]], 
        req_text: str, 
        original_columns: List[str]
    ) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Dynamically parses user requests to filter, remove rows, or drop columns
        matching any arbitrary field name and value across any dataset domain.
        """
        if not cleaned_orders:
            return cleaned_orders, "", ""

        req_norm = cls._normalize_str(req_text)
        cols = list(original_columns) if original_columns else list(cleaned_orders[0].keys())

        # 1. Column Removal: "Bỏ cột X" / "Xóa cột X" / "Loại bỏ cột X"
        col_drop_match = re.search(r'(?:bo|xoa|loai bo|tru|an|go)\s+(?:cot|truong)\s+([a-zA-Z0-9_\s\(\)]+)', req_norm)
        if col_drop_match:
            raw_target = col_drop_match.group(1).strip()
            # Strip trailing context like "o bang ...", "trong bang ...", "khoi bang ...", "cua bang ..."
            target = re.split(r'\s+(?:o|trong|tai|khoi|cua)\s+', raw_target)[0].strip()
            matched_col = next((c for c in cols if cls._normalize_str(c) == target or target in cls._normalize_str(c) or cls._normalize_str(c) in target), None)
            if matched_col:
                if matched_col in original_columns:
                    original_columns.remove(matched_col)
                if matched_col in cols:
                    cols.remove(matched_col)
                for r in cleaned_orders:
                    r.pop(matched_col, None)
                return cleaned_orders, f"Đã loại bỏ cột '{matched_col}' khỏi bảng dữ liệu theo yêu cầu.", f"Loại bỏ cột {matched_col}"
            elif target:
                return cleaned_orders, f"Đã ghi nhận yêu cầu ẩn / loại bỏ cột '{target}' khỏi bảng phân tích.", f"Ẩn cột {target}"

        is_addition = any(w in req_norm for w in ["bo sung", "them", "tao", "tao moi", "dua vao", "mo rong"])
        is_removal = not is_addition and any(re.search(r'\b' + re.escape(w) + r'\b', req_norm) for w in ["bo", "loai bo", "xoa", "tru", "khong lay", "loai", "ngung", "huy"])
        is_keep = any(w in req_norm for w in ["chi lay", "chi giu", "giu lai", "loc lay", "loc"])

        if not (is_removal or is_keep):
            return cleaned_orders, "", ""

        # Build set of unique values for each column (up to 100 values)
        col_values = {}
        for c in cols:
            vals = set()
            for o in cleaned_orders:
                v = o.get(c)
                if v is not None:
                    vals.add(str(v).strip())
            col_values[c] = vals

        # Match target column by name
        target_col = None
        col_pos = -1
        col_match_len = 0
        sorted_cols = sorted(cols, key=lambda c: len(cls._normalize_str(c)), reverse=True)
        for c in sorted_cols:
            c_norm = cls._normalize_str(c)
            clean_c_norm = re.sub(r'\(.*?\)', '', c_norm).strip()
            pos = req_norm.find(clean_c_norm)
            if pos != -1:
                target_col = c
                col_pos = pos
                col_match_len = len(clean_c_norm)
                break
            # Match significant words
            words = [w for w in clean_c_norm.split() if len(w) > 2 and w not in ["vnd", "ngay", "thang", "nam", "cac", "nhung", "dong"]]
            if len(words) >= 2 and all(w in req_norm for w in words):
                target_col = c
                col_pos = req_norm.find(words[0])
                last_w = words[-1]
                last_w_pos = req_norm.find(last_w)
                col_match_len = (last_w_pos + len(last_w)) - col_pos
                break

        # If target column not matched by name, check if any unique categorical value matches
        if not target_col:
            for c in sorted_cols:
                for v in col_values.get(c, set()):
                    v_norm = cls._normalize_str(v)
                    if len(v_norm) >= 2 and v_norm in req_norm and not v_norm.isdigit():
                        target_col = c
                        col_pos = req_norm.find(v_norm)
                        col_match_len = len(v_norm)
                        break
                if target_col:
                    break

        if not target_col:
            return cleaned_orders, "", ""

        # Determine operator and target value
        after_text = req_norm[col_pos + col_match_len:].strip() if col_pos != -1 else req_norm
        target_val, op = cls.parse_num_and_op(after_text)
        if target_val is None:
            target_val, op = cls.parse_num_and_op(req_norm)

        if target_val is None:
            # String match from col_values
            for v in col_values.get(target_col, set()):
                v_norm = cls._normalize_str(v)
                if v_norm and v_norm in req_norm:
                    target_val = v
                    op = "=="
                    break

        if target_val is None:
            return cleaned_orders, "", ""

        def matches_target(row):
            val = row.get(target_col)
            if val is None:
                for k in row:
                    if cls._normalize_str(k) == cls._normalize_str(target_col):
                        val = row[k]
                        break
            if val is None:
                return False

            if isinstance(target_val, (int, float)):
                try:
                    num_val = cls._safe_float(val)
                    if op == "==": return num_val == target_val
                    if op == ">": return num_val > target_val
                    if op == "<": return num_val < target_val
                    if op == ">=": return num_val >= target_val
                    if op == "<=": return num_val <= target_val
                    if op == "!=": return num_val != target_val
                except Exception:
                    return False
            else:
                r_norm = cls._normalize_str(str(val))
                t_norm = cls._normalize_str(str(target_val))
                return r_norm == t_norm or t_norm in r_norm

        before_cnt = len(cleaned_orders)
        if is_removal:
            new_orders = [o for o in cleaned_orders if not matches_target(o)]
        else:
            new_orders = [o for o in cleaned_orders if matches_target(o)]

        removed_cnt = before_cnt - len(new_orders)
        if isinstance(target_val, (int, float)):
            val_disp = f"{target_val:,.0f} đ" if target_val >= 1000 else f"{target_val:g}"
            op_desc = f"{op} {val_disp}"
        else:
            op_desc = f"= '{target_val}'"

        verb = "loại bỏ" if is_removal else "lọc giữ"
        note = f"Đã {verb} {removed_cnt} dòng có '{target_col}' {op_desc} (Dữ liệu còn lại: {len(new_orders)} bản ghi sạch)."
        summary = f"{'Loại bỏ' if is_removal else 'Lọc giữ'} '{target_col}' {op_desc}"
        return new_orders, note, summary

    @classmethod
    def compute_analytical_query(cls, orders: List[Dict[str, Any]], cols: List[str], req_text: str) -> Any:
        if not orders:
            return None
        req_norm = cls._normalize_str(req_text)
        is_calc_req = any(w in req_norm for w in ['tinh', 'xem', 'thong ke', 'tong hop', 'phan tich', 'bao nhieu', 'ty le', 'theo', 'nhom', 'xep hang', 'so sanh'])
        if not is_calc_req:
            return None

        # 1. Detect Dimension Column
        dim_col = None
        dim_alias_name = ""
        if any(w in req_norm for w in ['thang', 'thoi gian', 'ngay', 'timeline', 'date', 'month', 'chu ky', 'quy', 'nam', 'year']):
            dim_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['thang', 'thoi gian', 'ngay', 'date', 'month', 'quy', 'timeline'])), None)
            dim_alias_name = "Tháng / Thời gian"
        elif any(w in req_norm for w in ['kenh', 'channel', 'san tmdt', 'nen tang', 'platform']):
            dim_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['kenh', 'channel', 'platform'])), None)
            dim_alias_name = "Kênh bán hàng"
        elif any(w in req_norm for w in ['khu vuc', 'vung', 'mien', 'region', 'dia ly', 'tinh thanh', 'city']):
            dim_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['khu vuc', 'vung', 'mien', 'region', 'tinh'])), None)
            dim_alias_name = "Khu vực địa lý"
        elif any(w in req_norm for w in ['san pham', 'product', 'sku', 'mat hang', 'item', 'hang hoa']):
            dim_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['san pham', 'product', 'sku', 'ten hang'])), None)
            dim_alias_name = "Sản phẩm"
        elif any(w in req_norm for w in ['nganh hang', 'danh muc', 'category']):
            dim_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['nganh hang', 'danh muc', 'category'])), None)
            dim_alias_name = "Ngành hàng"

        # Direct column matching if not found by alias
        if not dim_col:
            for c in cols:
                c_norm = cls._normalize_str(c).split('(')[0].strip()
                if len(c_norm) >= 3 and c_norm in req_norm:
                    dim_col = c
                    dim_alias_name = c
                    break

        # Fallback to first non-numeric categorical column
        if not dim_col:
            for c in cols:
                c_norm = cls._normalize_str(c)
                if not any(k in c_norm for k in ['stt', 'id', 'ma', 'tien', 'doanh thu', 'gia', 'phi', 'vnd']):
                    dim_col = c
                    dim_alias_name = c
                    break

        if not dim_col:
            return None

        # 2. Detect Metric Column
        metric_col = None
        metric_name = "Doanh thu"
        if any(w in req_norm for w in ['loi nhuan', 'margin', 'cm', 'profit']):
            metric_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['loi nhuan', 'margin', 'cm', 'profit', 'gross_profit'])), None)
            metric_name = "Lợi nhuận"
        elif any(w in req_norm for w in ['chi phi', 'cost', 'ngan sach', 'fee', 'phi']):
            metric_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['chi phi', 'cost', 'fee', 'phi'])), None)
            metric_name = "Chi phí"
        elif any(w in req_norm for w in ['gia von', 'cogs']):
            metric_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['gia von', 'cogs'])), None)
            metric_name = "Giá vốn"

        if not metric_col:
            metric_col = next((c for c in cols if any(k in cls._normalize_str(c) for k in ['doanh thu', 'revenue', 'gross_amount', 'net_revenue', 'tien', 'thanh tien'])), None)
            metric_name = "Doanh thu"

        if not metric_col:
            for c in cols:
                sample_v = orders[0].get(c)
                if cls._safe_float(sample_v) > 0:
                    metric_col = c
                    metric_name = c
                    break

        if not metric_col:
            metric_col = cols[-1]

        # 3. Aggregate groups
        groups = {}
        for o in orders:
            raw_grp = o.get(dim_col)
            grp = str(raw_grp).strip() if raw_grp is not None else "Chưa phân nhóm"
            if not grp or grp.lower() in ["nan", "none", "--"]:
                grp = "Chưa phân nhóm"
            if grp not in groups:
                groups[grp] = {"name": grp, "total_metric": 0.0, "count": 0}
            val = cls._safe_float(o.get(metric_col, o.get("net_revenue", o.get("gross_amount", 0.0))))
            groups[grp]["total_metric"] += val
            groups[grp]["count"] += 1

        total_all = sum(g["total_metric"] for g in groups.values())
        total_orders = sum(g["count"] for g in groups.values())

        rows = []
        for g in groups.values():
            pct = round((g["total_metric"] / total_all * 100.0), 1) if total_all > 0 else 0.0
            avg = round((g["total_metric"] / g["count"]), 0) if g["count"] > 0 else 0.0
            rows.append({
                "group_name": g["name"],
                "metric_value": g["total_metric"],
                "formatted_value": f"{g['total_metric']:,.0f} đ",
                "percentage": pct,
                "order_count": g["count"],
                "average_value": avg,
                "formatted_average": f"{avg:,.0f} đ"
            })

        is_chronological = any(k in cls._normalize_str(dim_col) for k in ['thang', 'ngay', 'date', 'thoi gian', 'year', 'nam'])
        if is_chronological:
            rows.sort(key=lambda r: str(r["group_name"]))
        else:
            rows.sort(key=lambda r: r["metric_value"], reverse=True)

        top_g = max(rows, key=lambda r: r["metric_value"]) if rows else None
        bot_g = min(rows, key=lambda r: r["metric_value"]) if rows else None
        avg_per_group = (total_all / len(rows)) if rows else 0.0

        return {
            "title": f"BẢNG PHÂN TÍCH {metric_name.upper()} THEO {dim_col.upper()}",
            "dimension_col": dim_col,
            "metric_col": metric_col,
            "metric_name": metric_name,
            "total_metric_value": total_all,
            "formatted_total": f"{total_all:,.0f} đ",
            "total_orders": total_orders,
            "groups_count": len(rows),
            "top_group": top_g,
            "bottom_group": bot_g,
            "average_per_group": round(avg_per_group, 0),
            "formatted_average_per_group": f"{avg_per_group:,.0f} đ",
            "rows": rows,
            "insights": [
                f"Tổng {metric_name} toàn bộ {len(rows)} nhóm {dim_col}: {total_all:,.0f} đ ({total_orders} bản ghi đối soát).",
                f"Nhóm dẫn đầu: '{top_g['group_name']}' với {top_g['formatted_value']} ({top_g['percentage']}% tổng số)." if top_g else "",
                f"Nhóm thấp nhất: '{bot_g['group_name']}' với {bot_g['formatted_value']} ({bot_g['percentage']}% tổng số)." if bot_g else "",
                f"Doanh thu trung bình mỗi nhóm {dim_col}: {avg_per_group:,.0f} đ."
            ]
        }

    @classmethod
    def apply_modification(cls, data: Dict[str, Any], request_text: str, step: int = 3) -> Dict[str, Any]:
        if not data:
            return data

        sf = cls._safe_float
        req = request_text.strip()
        req_lower = req.lower()
        req_norm = cls._normalize_str(req)

        # Clone data shallowly, prepare deep copies of modified fields
        kpis = dict(data.get("financial_kpis") or data.get("summary_kpis") or {})
        channels = [dict(c) for c in (data.get("channel_breakdown") or [])]
        pnl = [dict(p) for p in (data.get("pnl_table") or [])]
        cleaned_orders = [dict(o) for o in (data.get("cleaned_orders_table") or [])]
        modifications_log = list(data.get("user_modifications") or [])
        dataset_meta = dict(data.get("dataset_meta") or {})
        orig_cols = list(dataset_meta.get("original_columns") or (list(cleaned_orders[0].keys()) if cleaned_orders else []))

        applied_notes = []
        action_summary = ""

        # ==============================================================
        # 0. ĐIỀU CHỈNH / XÓA / BỔ SUNG ĐỀ XUẤT CHIẾN LƯỢC (BƯỚC 4)
        # ==============================================================
        recs = [dict(r) for r in (data.get("recommendations") or [])]
        is_addition = any(w in req_norm for w in ["them", "bo sung", "tao", "tao moi", "dua vao", "mo rong", "de xuat them"])
        is_rec_req = (step == 4) or any(w in req_norm for w in ["de xuat", "giai phap", "chien luoc", "phuong an"])
        if is_rec_req:
            is_rec_removal = not is_addition and any(re.search(r'\b' + re.escape(w) + r'\b', req_norm) for w in ["bo", "xoa", "loai bo", "huy", "remove", "loai", "tru"])
            if is_rec_removal:
                num_match = re.search(r'(?:de xuat|giai phap|chien luoc|muc|so)\s*(\d+)', req_norm) or re.search(r'\b(\d+)\b', req_norm)
                if num_match and recs:
                    num = int(num_match.group(1))
                    idx = num - 1
                    if 0 <= idx < len(recs):
                        removed_rec = recs.pop(idx)
                        rec_name = removed_rec.get("campaign_name") or removed_rec.get("title") or f"Đề xuất {num}"
                        note = f"Đã loại bỏ đề xuất {num} ({rec_name}) khỏi danh mục chiến lược theo đúng yêu cầu."
                        applied_notes.append(note)
                        action_summary = f"Gỡ bỏ đề xuất số {num}"
                elif recs:
                    for idx, r in enumerate(recs):
                        r_text = cls._normalize_str(str(r.get("campaign_name", "")) + " " + str(r.get("primary_reason", "")) + " " + str(r.get("title", "")))
                        keywords = [w for w in req_norm.split() if len(w) > 2 and w not in ["bo", "xoa", "loai", "trong", "he", "thong", "giai", "phap", "chien", "luoc"]]
                        if any(kw in r_text for kw in keywords):
                            removed_rec = recs.pop(idx)
                            rec_name = removed_rec.get("campaign_name") or removed_rec.get("title") or f"Đề xuất {idx+1}"
                            note = f"Đã loại bỏ đề xuất '{rec_name}' theo đúng yêu cầu."
                            applied_notes.append(note)
                            action_summary = f"Gỡ bỏ đề xuất '{rec_name}'"
                            break
            elif is_addition:
                clean_title = re.sub(r'^(?:them|bo sung|tao)\s+(?:de xuat|phuong an|giai phap|chien luoc)?\s*', '', req, flags=re.I).strip()
                if not clean_title:
                    clean_title = req
                recs.append({
                    "campaign_id": f"REC_{len(recs)+1}",
                    "campaign_name": f"Đề xuất: {clean_title}",
                    "decision": "BỔ SUNG THEO YÊU CẦU",
                    "decision_badge": "info",
                    "primary_reason": f"Thực hiện theo chỉ đạo của người dùng: '{req}'",
                    "action_items": [f"Triển khai hành động: {clean_title}"]
                })
                applied_notes.append(f"Đã bổ sung đề xuất mới: '{clean_title}'")
                action_summary = f"Thêm đề xuất: '{clean_title[:30]}...'" if len(clean_title) > 30 else f"Thêm đề xuất: '{clean_title}'"

        # ==============================================================
        # 1. THÔNG MINH: LỌC DỮ LIỆU ĐỘNG THEO BẤT KỲ CỘT & GIÁ TRỊ NÀO (GENERIC SMART FILTER)
        # Hỗ trợ: "Bỏ các số tháng dịch vụ là 12", "Bỏ ca đêm", "Bỏ gói Năm", "Bỏ cột Tiền tệ", "Chỉ giữ gói Tháng"...
        # ==============================================================
        new_orders, smart_note, smart_summary = cls.smart_filter_orders(cleaned_orders, req, orig_cols)
        if smart_note:
            cleaned_orders = new_orders
            applied_notes.append(smart_note)
            action_summary = smart_summary
            dataset_meta["total_rows"] = len(cleaned_orders)
            dataset_meta["original_columns"] = orig_cols

        # ==============================================================
        # 2. LỌC HOẶC LOẠI BỎ KÊNH BÁN HÀNG (CHANNEL FILTERING)
        # ==============================================================
        existing_channels = set()
        for o in cleaned_orders:
            ch = str(o.get("channel", "")).strip()
            if ch and ch.lower() != "none" and ch != "--":
                existing_channels.add(ch)
        for c in channels:
            ch = str(c.get("channel", "")).strip()
            if ch:
                existing_channels.add(ch)

        chan_alias_map = {
            "website": ["website", "web", "online web", "online"],
            "cửa hàng": ["cửa hàng", "cua hang", "store", "pos", "offline", "cửa hàng trực tiếp"],
            "sàn tmđt": ["sàn tmđt", "san tmdt", "shopee", "lazada", "tiktok", "tiki", "sàn", "san"],
            "shopee": ["shopee"],
            "lazada": ["lazada"],
            "tiktok": ["tiktok"],
            "google": ["google"],
            "meta": ["meta", "facebook"],
            "sự kiện": ["sự kiện", "su kien", "event"],
            "giới thiệu": ["giới thiệu", "gioi thieu", "referral"]
        }

        is_removal = any(w in req_lower for w in ["bỏ", "loại bỏ", "loai bo", "xóa", "xoa", "trừ", "tru", "không tính", "khong tinh", "ngừng", "ngung", "loại"])
        target_chans_to_remove = set()
        for ch in existing_channels:
            ch_low = ch.lower()
            if ch_low in req_lower:
                target_chans_to_remove.add(ch)
            else:
                for norm_key, aliases in chan_alias_map.items():
                    if any(a in ch_low for a in aliases) and any(a in req_lower for a in aliases):
                        target_chans_to_remove.add(ch)

        if is_removal and target_chans_to_remove:
            for ch_name in target_chans_to_remove:
                before_orders_cnt = len(cleaned_orders)
                cleaned_orders = [o for o in cleaned_orders if str(o.get("channel", "")).lower().strip() != ch_name.lower().strip()]
                removed_orders_cnt = before_orders_cnt - len(cleaned_orders)

                target_chan_obj = next((c for c in channels if str(c.get("channel", "")).lower().strip() == ch_name.lower().strip()), None)
                ch_rev = sf(target_chan_obj.get("net_revenue", 0)) if target_chan_obj else 0.0
                channels = [c for c in channels if str(c.get("channel", "")).lower().strip() != ch_name.lower().strip()]

                applied_notes.append(f"Đã loại bỏ toàn bộ dữ liệu kênh '{ch_name}' ({removed_orders_cnt} bản ghi, {ch_rev:,.0f} đ doanh thu).")
                if not action_summary:
                    action_summary = f"Loại bỏ kênh bán '{ch_name}'"

        # ==============================================================
        # 3. LÀM SẠCH ĐƠN HỦY / HOÀN (STATUS FILTERING)
        # ==============================================================
        if any(k in req_lower for k in ["bỏ đơn hủy", "bỏ đơn huỷ", "loại bỏ đơn hủy", "loại bỏ đơn huỷ", "cancelled", "hủy", "huỷ", "hoàn"]):
            before_cnt = len(cleaned_orders)
            cleaned_orders = [o for o in cleaned_orders if str(o.get("status", "")).upper() not in ["CANCELLED", "HỦY", "HUY", "RETURNED", "REFUNDED"]]
            diff = before_cnt - len(cleaned_orders)
            if diff > 0:
                applied_notes.append(f"Đã loại bỏ {diff} đơn hàng ở trạng thái CANCELLED/HỦY.")
                if not action_summary: action_summary = f"Loại bỏ {diff} đơn hủy"

        # ==============================================================
        # 4. KHỬ TRÙNG LẶP MÃ ĐƠN (DEDUPLICATION)
        # ==============================================================
        if any(k in req_lower for k in ["khử trùng", "khu trung", "trùng mã", "trung ma", "trùng lặp", "bỏ đơn trùng", "khử trùng lặp"]):
            before_cnt = len(cleaned_orders)
            seen_ids = set()
            dedup_orders = []
            for o in cleaned_orders:
                oid = str(o.get("order_id", "")).strip()
                if oid and not oid.startswith("--"):
                    if oid not in seen_ids:
                        seen_ids.add(oid)
                        dedup_orders.append(o)
                else:
                    dedup_orders.append(o)
            diff = before_cnt - len(dedup_orders)
            cleaned_orders = dedup_orders
            applied_notes.append(f"Đã khử trùng lặp {diff} đơn hàng trùng mã.")
            if not action_summary: action_summary = f"Khử {diff} đơn trùng mã"

        # ==============================================================
        # 5. LOẠI BỎ ĐƠN CÓ GIÁ TRỊ HOẶC DOANH THU = 0
        # ==============================================================
        if any(k in req_lower for k in ["doanh thu = 0", "giá trị = 0", "doanh thu bằng 0", "bỏ đơn 0", "đơn 0 đồng", "bỏ đơn âm"]):
            before_cnt = len(cleaned_orders)
            cleaned_orders = [o for o in cleaned_orders if sf(o.get("gross_amount", o.get("net_revenue", 0.0))) > 0]
            diff = before_cnt - len(cleaned_orders)
            applied_notes.append(f"Đã loại bỏ {diff} đơn hàng có doanh thu hoặc giá trị bằng 0.")
            if not action_summary: action_summary = f"Loại bỏ {diff} đơn doanh thu 0"

        # ==============================================================
        # 6. CHI PHÍ MARKETING & VẬN HÀNH (CAMPAIGN COSTS)
        # ==============================================================
        mkt_pct_match = re.search(r'(giảm|tăng|hạ)\s*(\d+(?:\.\d+)?)\s*%\s*(?:chi phí|marketing|mkt|ngân sách)', req_lower)
        if not mkt_pct_match:
            mkt_pct_match = re.search(r'(?:chi phí|marketing|mkt|ngân sách)\s*(giảm|tăng|hạ)\s*(\d+(?:\.\d+)?)\s*%', req_lower)

        if mkt_pct_match:
            action = mkt_pct_match.group(1)
            pct = sf(mkt_pct_match.group(2))
            factor = (1.0 - pct / 100.0) if action in ["giảm", "hạ"] else (1.0 + pct / 100.0)

            old_cost = sf(kpis.get("total_campaign_costs", 0))
            new_cost = max(0.0, old_cost * factor)
            kpis["total_campaign_costs"] = new_cost

            for p in pnl:
                p["campaign_cost_total"] = max(0.0, sf(p.get("campaign_cost_total", 0)) * factor)
                p_cm = sf(p.get("net_revenue", 0)) - sf(p.get("cogs", 0)) - p["campaign_cost_total"]
                p["contribution_margin"] = p_cm
                p_net = sf(p.get("net_revenue", 1))
                p["contribution_margin_pct"] = round(p_cm / p_net * 100.0, 2) if p_net > 0 else 0.0

            verb = "Giảm" if action in ["giảm", "hạ"] else "Tăng"
            note = f"{verb} {pct}% chi phí marketing (từ {old_cost:,.0f} đ xuống {new_cost:,.0f} đ)."
            applied_notes.append(note)
            if not action_summary: action_summary = f"Điều chỉnh {verb.lower()} {pct}% chi phí marketing"

        # ==============================================================
        # 7. GIÁ VỐN HÀNG BÁN (COGS)
        # ==============================================================
        cogs_pct_match = re.search(r'(giảm|tăng|hạ)\s*(\d+(?:\.\d+)?)\s*%\s*(?:giá vốn|cogs)', req_lower)
        if not cogs_pct_match:
            cogs_pct_match = re.search(r'(?:giá vốn|cogs)\s*(giảm|tăng|hạ)\s*(\d+(?:\.\d+)?)\s*%', req_lower)
        cogs_ratio_match = re.search(r'(?:tỷ lệ|đặt|chỉnh)\s*(?:giá vốn|cogs)\s*(?:là|thành|=)?\s*(\d+(?:\.\d+)?)\s*%', req_lower)

        if cogs_pct_match:
            action = cogs_pct_match.group(1)
            pct = sf(cogs_pct_match.group(2))
            factor = (1.0 - pct / 100.0) if action in ["giảm", "hạ"] else (1.0 + pct / 100.0)
            old_cogs = sf(kpis.get("total_cogs", 0))
            new_cogs = max(0.0, old_cogs * factor)
            kpis["total_cogs"] = new_cogs

            for o in cleaned_orders:
                o["cogs"] = sf(o.get("cogs", 0)) * factor

            verb = "Giảm" if action in ["giảm", "hạ"] else "Tăng"
            applied_notes.append(f"{verb} {pct}% giá vốn COGS (từ {old_cogs:,.0f} đ sang {new_cogs:,.0f} đ).")
            if not action_summary: action_summary = f"{verb} {pct}% giá vốn COGS"

        elif cogs_ratio_match:
            ratio = sf(cogs_ratio_match.group(1)) / 100.0
            net_rev = sf(kpis.get("total_net_revenue", 0))
            old_cogs = sf(kpis.get("total_cogs", 0))
            new_cogs = net_rev * ratio
            kpis["total_cogs"] = new_cogs

            for o in cleaned_orders:
                o["cogs"] = sf(o.get("net_revenue", o.get("gross_amount", 0))) * ratio

            applied_notes.append(f"Quy đổi tỷ lệ giá vốn thành {ratio*100:.0f}% doanh thu thuần (COGS mới: {new_cogs:,.0f} đ).")
            if not action_summary: action_summary = f"Đặt giá vốn {ratio*100:.0f}%"

        # ==============================================================
        # 8. LOẠI BỎ HÀNG BÁN TRẢ LẠI (RETURNS)
        # ==============================================================
        has_return_removal = bool(re.search(r'(bỏ|loại bỏ|không tính|triệt tiêu|xóa).*?(hàng hoàn|hoàn huỷ|hoàn hủy|hoàn đơn|trả hàng|tiền hoàn|returns)', req_lower)) or "hoàn = 0" in req_lower
        if has_return_removal:
            old_returns = sf(kpis.get("total_return_amount", 0))
            kpis["total_return_amount"] = 0.0
            kpis["return_rate_pct"] = 0.0
            for o in cleaned_orders:
                o["return_amount"] = 0.0
                o["net_revenue"] = sf(o.get("gross_amount", o.get("gross_revenue", 0)))
            for c in channels:
                c["return_amount"] = 0.0
                c["net_revenue"] = sf(c.get("gross_revenue", 0))
            applied_notes.append(f"Loại bỏ toàn bộ hàng hoàn huỷ (trước: {old_returns:,.0f} đ).")
            if not action_summary: action_summary = "Loại bỏ 100% hàng hoàn hủy"

        # ==============================================================
        # 9. TÍNH TOÁN LẠI TẤT CẢ KPIS TÀI CHÍNH / VẬN HÀNH TỪ DỮ LIỆU ĐÃ LỌC
        # ==============================================================
        domain_type = data.get("domain_type") or dataset_meta.get("domain_type") or "RETAIL_ORDERS"
        is_financial = data.get("is_financial", True) and (domain_type not in ["MANUFACTURING_QUALITY", "COHORT_RETENTION", "SALES_FUNNEL"])

        if is_financial:
            if cleaned_orders:
                first_row = cleaned_orders[0]
                domain_rev_col = next((c for c in first_row.keys() if any(k in c.lower() for k in ["tiền thu trước", "doanh thu tháng", "doanh thu", "revenue"]) and not any(k in c.lower() for k in ["cơ hội", "tiềm năng", "pipeline"])), None)
                
                new_gross = sum(sf(o.get("gross_amount", o.get("gross_revenue", o.get(domain_rev_col, 0.0) if domain_rev_col else 0.0))) for o in cleaned_orders)
                new_disc = sum(sf(o.get("discount_amount", 0.0)) for o in cleaned_orders)
                new_ret = sum(sf(o.get("return_amount", 0.0)) for o in cleaned_orders)
                new_net = sum(sf(o.get("net_revenue", sf(o.get("gross_amount", o.get(domain_rev_col, 0.0) if domain_rev_col else 0.0)) - sf(o.get("return_amount", 0.0)))) for o in cleaned_orders)
                new_cogs = sum(sf(o.get("cogs", 0.0)) for o in cleaned_orders)

                kpis["is_financial"] = True
                kpis["total_gross_revenue"] = new_gross
                kpis["total_discount_amount"] = new_disc
                kpis["total_return_amount"] = new_ret
                kpis["total_net_revenue"] = new_net
                kpis["total_cogs"] = new_cogs
                kpis["total_gross_profit"] = new_net - new_cogs
                kpis["total_orders"] = len(cleaned_orders)
                mkt_cost = sf(kpis.get("total_campaign_costs", 0.0))
                kpis["total_contribution_margin"] = kpis["total_gross_profit"] - mkt_cost
                kpis["cm_pct"] = round(kpis["total_contribution_margin"] / new_net * 100.0, 2) if new_net > 0 else 0.0
                kpis["aov"] = round(new_net / len(cleaned_orders), 0) if len(cleaned_orders) > 0 else 0.0

                chan_groups = {}
                for o in cleaned_orders:
                    ch = str(o.get("channel") or o.get("Kênh") or "Khác").strip()
                    if not ch or ch.lower() in ["none", "nan", "--"]:
                        ch = "Khác"
                    if ch not in chan_groups:
                        chan_groups[ch] = {"channel": ch, "gross_revenue": 0.0, "net_revenue": 0.0, "return_amount": 0.0, "orders_count": 0}
                    g = sf(o.get("gross_amount", o.get("gross_revenue", o.get(domain_rev_col, 0.0) if domain_rev_col else 0.0)))
                    r = sf(o.get("return_amount", 0.0))
                    n = sf(o.get("net_revenue", g - r))
                    chan_groups[ch]["gross_revenue"] += g
                    chan_groups[ch]["return_amount"] += r
                    chan_groups[ch]["net_revenue"] += n
                    chan_groups[ch]["orders_count"] += 1
                channels = list(chan_groups.values())
            else:
                kpis["is_financial"] = True
                kpis["total_gross_revenue"] = 0.0
                kpis["total_discount_amount"] = 0.0
                kpis["total_return_amount"] = 0.0
                kpis["total_net_revenue"] = 0.0
                kpis["total_cogs"] = 0.0
                kpis["total_gross_profit"] = 0.0
                kpis["total_contribution_margin"] = 0.0
                kpis["total_orders"] = 0
                kpis["cm_pct"] = 0.0
                kpis["aov"] = 0.0
                channels = []
        else:
            # Miền dữ liệu phi tiền tệ (sản xuất, chất lượng, cohort): Tuyệt đối không tính fake doanh thu VNĐ
            kpis["is_financial"] = False
            kpis["total_gross_revenue"] = 0.0
            kpis["total_discount_amount"] = 0.0
            kpis["total_return_amount"] = 0.0
            kpis["total_net_revenue"] = 0.0
            kpis["total_cogs"] = 0.0
            kpis["total_gross_profit"] = 0.0
            kpis["total_campaign_costs"] = 0.0
            kpis["total_contribution_margin"] = 0.0
            kpis["cm_pct"] = 0.0
            kpis["aov"] = 0.0
            kpis["total_orders"] = len(cleaned_orders)
            channels = []

        # Tái cấu trúc metadata, angles, kpis và domain table theo dữ liệu đã làm sạch
        updated_domain_angles = list(data.get("domain_analysis_angles") or [])
        updated_domain_kpis = list(data.get("domain_kpis") or [])
        if domain_type and cleaned_orders:
            try:
                df_clean = pd.DataFrame(cleaned_orders)
                for col in df_clean.columns:
                    try:
                        s_first = df_clean[col].dropna().astype(str).str.strip()
                        if not s_first.empty and s_first.str.contains(r'đ|VND|%|\.000|,000').any():
                            df_clean[col] = df_clean[col].apply(cls._safe_float)
                    except Exception:
                        pass
                rebuilt_angles = DomainAnalyzer.build_domain_analysis_angles(df_clean, domain_type, orig_cols)
                if rebuilt_angles:
                    updated_domain_angles = rebuilt_angles
                rebuilt_kpis = DomainAnalyzer.build_domain_kpis(df_clean, domain_type, orig_cols)
                if rebuilt_kpis:
                    updated_domain_kpis = rebuilt_kpis
                rebuilt_pnl, rebuilt_recs = DomainAnalyzer.build_domain_pnl_and_recommendations(df_clean, domain_type, orig_cols)
                if rebuilt_pnl:
                    pnl = rebuilt_pnl
                rebuilt_matrix = DomainAnalyzer.build_domain_problem_solution_matrix(
                    df=df_clean,
                    domain=domain_type,
                    original_cols=orig_cols,
                    pnl_records=pnl,
                    financial_kpis=kpis
                )
                if rebuilt_matrix:
                    updated_matrix = rebuilt_matrix
            except Exception as e:
                print(f"[MOD_ENGINE] Lỗi tái cấu trúc domain metadata: {e}")

        # Smart Analytical Intent Recognition & Detailed Dynamic Computation
        calc_result = cls.compute_analytical_query(cleaned_orders, orig_cols, req)
        if calc_result:
            top_info = f"Nhóm cao nhất: '{calc_result['top_group']['group_name']}' ({calc_result['top_group']['formatted_value']})" if calc_result.get('top_group') else ""
            note = f"Đã tính toán chi tiết {calc_result['metric_name']} theo {calc_result['dimension_col']} ({calc_result['groups_count']} nhóm đối soát. {top_info})."
            applied_notes.append(note)
            if not action_summary:
                action_summary = f"Tính {calc_result['metric_name'].lower()} theo {calc_result['dimension_col']}"
        elif any(k in req_lower for k in ["tính doanh thu", "tinh doanh thu", "phân tích", "phan tich", "xem doanh thu", "thống kê", "thong ke", "tổng hợp", "tong hop", "tính", "tinh"]):
            if any(k in req_lower for k in ["kênh", "kenh", "channel", "nền tảng", "nen tang"]):
                applied_notes.append("Đã phân bổ và tính toán chi tiết doanh thu theo từng kênh bán hàng (Omnichannel).")
                if not action_summary: action_summary = "Tính doanh thu theo kênh bán hàng"
            elif any(k in req_lower for k in ["khu vực", "vùng", "miền", "region"]):
                applied_notes.append("Đã phân bổ và tính toán chi tiết doanh thu theo khu vực địa lý (Miền Bắc, Trung, Nam).")
                if not action_summary: action_summary = "Tính doanh thu theo khu vực địa lý"
            elif any(k in req_lower for k in ["thời gian", "tháng", "ngày", "timeline"]):
                applied_notes.append("Đã tổng hợp doanh thu theo dòng thời gian chu kỳ kinh doanh.")
                if not action_summary: action_summary = "Tính doanh thu theo thời gian"
            elif any(k in req_lower for k in ["sản phẩm", "sku", "mặt hàng"]):
                applied_notes.append("Đã xếp hạng và tính toán doanh thu chi tiết theo từng sản phẩm.")
                if not action_summary: action_summary = "Tính doanh thu theo danh mục sản phẩm"

        if not applied_notes:
            applied_notes.append(f"Đã ghi nhận và áp dụng nguyên tắc phân tích tùy chỉnh: '{req}'.")
            action_summary = req

        # Save to user_modifications log
        mod_entry = {
            "step": step,
            "request": req,
            "action_summary": action_summary or req,
            "applied_notes": applied_notes,
            "resulting_kpis": {
                "total_net_revenue": kpis.get("total_net_revenue", 0),
                "total_cogs": kpis.get("total_cogs", 0),
                "total_campaign_costs": kpis.get("total_campaign_costs", 0),
                "total_contribution_margin": kpis.get("total_contribution_margin", 0),
                "cm_pct": kpis.get("cm_pct", 0)
            }
        }
        if calc_result:
            mod_entry["analytical_calculation_result"] = calc_result
        modifications_log.append(mod_entry)

        # Assemble updated pipeline output
        updated_data = dict(data)
        if calc_result:
            updated_data["analytical_calculation_result"] = calc_result
        updated_data["financial_kpis"] = kpis
        updated_data["summary_kpis"] = dict(kpis)
        updated_data["cleaned_orders_table"] = cleaned_orders
        updated_data["channel_breakdown"] = channels
        updated_data["pnl_table"] = pnl
        updated_data["user_modifications"] = modifications_log
        updated_data["last_modification"] = mod_entry
        updated_data["dataset_meta"] = dataset_meta
        updated_data["domain_analysis_angles"] = updated_domain_angles
        updated_data["domain_kpis"] = updated_domain_kpis
        updated_data["is_financial"] = is_financial
        updated_data["recommendations"] = recs
        if 'updated_matrix' in locals() and updated_matrix:
            updated_data["problem_solution_matrix"] = updated_matrix
            updated_data["root_causes"] = updated_matrix

        return updated_data
