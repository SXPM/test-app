import os
import csv
import random
import sqlite3
import datetime
import tempfile
import flet as ft


# ============================================================
# 1. 数据目录 & 数据库
# ============================================================
def _resolve_data_dir():
    env_dir = os.environ.get("FLET_APP_STORAGE_DATA")
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    d = os.path.join(tempfile.gettempdir(), "wheel_tracker")
    os.makedirs(d, exist_ok=True)
    return d


DATA_DIR = _resolve_data_dir()
DB_PATH = os.path.join(DATA_DIR, "wheel_tracker.db")


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS records (
            date TEXT PRIMARY KEY,
            morning TEXT,
            evening TEXT,
            is_rest INTEGER DEFAULT 0,
            status INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


def seed_random_records(n=10):
    """随机造 n 条记录（日期不重复），用于测试导出。"""
    conn = get_conn()
    cursor = conn.cursor()
    base = datetime.date.today() - datetime.timedelta(days=n * 2)
    for i in range(n):
        d = (base + datetime.timedelta(days=i * 2)).strftime("%Y-%m-%d")
        morning = f"早{random.randint(1, 20)}km"
        evening = f"晚{random.randint(1, 20)}km"
        is_rest = random.choice([0, 0, 0, 1])
        cursor.execute("""
            INSERT INTO records (date, morning, evening, is_rest, status)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(date) DO UPDATE SET
                morning=excluded.morning,
                evening=excluded.evening,
                is_rest=excluded.is_rest
        """, (d, morning, evening, is_rest))
    conn.commit()
    conn.close()
    return n


# ============================================================
# 2. 导出核心（只干"生成文件"这件事，不碰对话框）
# ============================================================
def export_to_csv(csv_path):
    """把 records 表写成 CSV 文件，返回条数。
    用 utf-8-sig，Excel 打开不乱码。"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT date, morning, evening, is_rest, status FROM records ORDER BY date"
    )
    rows = cursor.fetchall()
    conn.close()

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "morning", "evening", "is_rest", "status"])
        writer.writerows(rows)
    return len(rows)


def export_to_db(dst_path):
    """用 sqlite 官方 backup 接口复制整个库，返回文件字节大小。"""
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return os.path.getsize(dst_path)


# ============================================================
# 3. Flet 页面
# ============================================================
def main(page: ft.Page):
    page.title = "导出测试"
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    init_db()

    # FilePicker 是 Service，挂 page.services
    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    status = ft.Text("", color=ft.Colors.GREEN)
    info = ft.Column([])

    def refresh_info():
        conn = get_conn()
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.close()
        info.controls.clear()
        info.controls.append(ft.Text(f"当前库记录数：{count}", weight=ft.FontWeight.BOLD))
        info.controls.append(
            ft.Text(f"数据目录：{DATA_DIR}", size=12, color=ft.Colors.GREY)
        )
        page.update()

    # -------- ① 随机造数据 --------
    def do_seed(e):
        n = seed_random_records(10)
        status.value = f"✅ 已随机生成 {n} 条测试记录"
        status.color = ft.Colors.GREEN
        refresh_info()

    # -------- ② 导出 CSV --------
    async def do_export_csv(e):
        status.value = "⏳ 正在准备导出 CSV…"
        status.color = ft.Colors.BLUE
        page.update()

        # 1. 先在后台生成 CSV 文件并读成 bytes
        csv_path = os.path.join(DATA_DIR, "temp_export.csv")
        try:
            n = export_to_csv(csv_path)
            with open(csv_path, "rb") as f:
                content_bytes = f.read()
        except Exception as err:
            status.value = f"❌ 准备导出数据失败：{err}"
            status.color = ft.Colors.RED
            page.update()
            return

        # 2. 把 bytes 交给 save_file
        #    Web：浏览器自动下载，存到默认下载目录
        #    桌面/手机：弹系统保存框，用户选路径
        try:
            await file_picker.save_file(
                dialog_title="保存 CSV",
                file_name="records_export.csv",
                allowed_extensions=["csv"],
                src_bytes=content_bytes,
            )
            status.value = f"✅ 已导出 {n} 条记录到 CSV"
            status.color = ft.Colors.GREEN
        except Exception as err:
            status.value = f"❌ 导出失败：{err}"
            status.color = ft.Colors.RED
        page.update()

    # -------- ③ 导出 db --------
    async def do_export_db(e):
        status.value = "⏳ 正在准备导出 db…"
        status.color = ft.Colors.BLUE
        page.update()

        # 1. 先在后台生成 db 副本并读成 bytes
        db_path = os.path.join(DATA_DIR, "temp_export.db")
        try:
            size = export_to_db(db_path)
            with open(db_path, "rb") as f:
                content_bytes = f.read()
        except Exception as err:
            status.value = f"❌ 准备导出数据失败：{err}"
            status.color = ft.Colors.RED
            page.update()
            return

        # 2. 把 bytes 交给 save_file
        try:
            await file_picker.save_file(
                dialog_title="保存数据库",
                file_name="records_export.db",
                allowed_extensions=["db"],
                src_bytes=content_bytes,
            )
            status.value = f"✅ 已导出数据库（{size} 字节）"
            status.color = ft.Colors.GREEN
        except Exception as err:
            status.value = f"❌ 导出失败：{err}"
            status.color = ft.Colors.RED
        page.update()

    # -------- 组装 --------
    page.add(
        ft.Text("📤 导出测试", size=22, weight=ft.FontWeight.BOLD),
        ft.ElevatedButton("① 随机造 10 条记录", on_click=do_seed),
        ft.Divider(),
        ft.ElevatedButton(
            "② 导出 CSV",
            on_click=lambda e: page.run_task(do_export_csv, e),
        ),
        ft.ElevatedButton(
            "③ 导出 db 文件",
            on_click=lambda e: page.run_task(do_export_db, e),
        ),
        status,
        ft.Divider(),
        info,
    )
    refresh_info()


ft.run(main, view=ft.AppView.WEB_BROWSER)