"""File and directory related CLI commands."""

from __future__ import annotations

import fnmatch
import json
import warnings

import typer

from cli.context import CLIContext
from cli.presentation import echo, render_error, secho, style

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="Using slow pure-python SequenceMatcher.*",
        category=UserWarning,
    )
    from fuzzywuzzy import fuzz

from cli.formatting import format_size, format_time
from cli.parsers import parse_date_to_aware_datetime, parse_size_to_bytes
from core.config import ConfigManager
from core.factory import get_storage_provider, parse_remote_path
from storage.base import DeleteCapability


def ls(
    path: str = typer.Argument(..., help="路徑格式: [remote_name]:/[remote_path]"),
    offset: int = typer.Option(0, "--offset", help="起始索引偏移量 (0-based)"),
    limit: int | None = typer.Option(None, "--limit", "-n", help="最大回傳項目數量"),
    json_output: bool = typer.Option(False, "--json", help="輸出穩定 JSON，適合腳本使用"),
):
    """
    列出指定雲端目錄下的檔案與資料夾（支援分頁範圍查詢）
    範例: python main.py ls work_sp:/Shared Documents --offset 0 --limit 20
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    try:
        # 1. 解析路徑
        remote_name, remote_path = parse_remote_path(path, config_manager.config.default_remote)
        if not json_output:
            secho(f"🔍 準備連線至節點: [{remote_name}], 路徑: {remote_path or '/'}", fg=typer.colors.CYAN)
        
        # 2. 初始化對應的 Storage Provider (會自動處理快取與認證)
        storage = get_storage_provider(remote_name, config_manager)
        
        # 3. 呼叫 API 取得檔案清單（以最少請求數取得指定範圍）
        items = storage.list_dir(remote_path, offset=offset, limit=limit)
        
        # 4. 顯示結果
        if json_output:
            echo(
                json.dumps(
                    {
                        "remote": remote_name,
                        "path": remote_path or "/",
                        "items": [item.model_dump(mode="json") for item in items],
                    },
                    ensure_ascii=False,
                )
            )
            return

        if not items:
            secho("目錄為空或找不到檔案。", fg=typer.colors.YELLOW)
            return
            
        secho(f"\n找到 {len(items)} 個項目:\n", fg=typer.colors.GREEN)
        
        for item in items:
            if item.is_dir:
                # 資料夾通常不顯示大小，或者顯示為 "-"
                secho(f"📁 {item.name}/", fg=typer.colors.BLUE, bold=True)
            else:
                # 套用剛寫好的 format_size
                size_str = format_size(item.size)
                
                # 處理時間 (如果 item.modified_at 是 datetime 物件，先轉成 iso 字串給 format_time 處理)
                if item.modified_at:
                    time_str = format_time(item.modified_at.isoformat())
                else:
                    time_str = "未知時間"
                
                # 使用 ljust 來對齊排版，讓畫面看起來更像專業的表格
                echo(f"📄 {item.name.ljust(40)} | 大小: {size_str.ljust(10)} | 修改時間: {time_str}")
            
    except ValueError as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "無法列出指定路徑。",
                cause=exc,
                next_steps=(
                    "確認路徑格式為 `REMOTE:/path`。",
                    "執行 `drive-unix remote list` 確認 Remote 名稱。",
                    "執行 `drive-unix ls --help` 查看參數說明。",
                ),
            )
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "讀取目錄失敗。",
                cause=exc,
                next_steps=(
                    "確認網路連線、Remote 認證與目錄權限。",
                    "執行 `drive-unix remote test <REMOTE>` 測試連線。",
                ),
            )
        raise typer.Exit(code=1) from exc

def show_tree(
    remote_path: str = typer.Argument(..., help="遠端路徑 (例如: my_sp:/Shared Documents)"),
    depth: int = typer.Option(None, "--depth", "-L", help="向下遞迴的最大深度 (不指定則無限遞迴)"),
    files_only: bool = typer.Option(False, "--files-only", help="視覺上僅顯示檔案節點"),
    dirs_only: bool = typer.Option(False, "--dirs-only", "-d", help="僅顯示資料夾節點"),
    max_items: int = typer.Option(1000, "--max-items", help="最大載入項目限制 (防爆保護機制)")
):
    """
    以樹狀結構列出遠端檔案與資料夾
    """
    if files_only and dirs_only:
        render_error(
            "參數互相衝突。",
            cause="--files-only 與 --dirs-only 不可同時使用。",
            next_steps=("只保留其中一個篩選選項後重試。",),
        )
        raise typer.Exit(code=1)

    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        remote_name, parsed_remote_path = parse_remote_path(remote_path, config_manager.config.default_remote)
        storage = get_storage_provider(remote_name, config_manager)

        # 根目錄顯示
        display_root = parsed_remote_path if parsed_remote_path.strip("/") else "/"
        secho(f"🌲 [{remote_name}] {display_root}", fg=typer.colors.CYAN, bold=True)

        # 使用閉包 (Closure) 來維持遞迴狀態
        state = {
            "count": 0,
            "max_items": max_items,
            "limit_reached": False
        }

        def walk_tree(current_path: str, prefix: str = "", current_depth: int = 1):
            if state["limit_reached"]:
                return

            try:
                # 這裡會呼叫我們寫好的分頁載入 list_dir
                items = storage.list_dir(current_path)
            except Exception as e:
                secho(f"{prefix}└── ❌ [無法讀取: {e}]", fg=typer.colors.RED)
                return

            # 若只需顯示資料夾，在此直接過濾
            if dirs_only:
                items = [i for i in items if i.is_dir]

            # 排序：資料夾優先，再來是檔案，最後依字母排序
            items.sort(key=lambda x: (not x.is_dir, x.name))

            for index, item in enumerate(items):
                if state["count"] >= state["max_items"]:
                    if not state["limit_reached"]:
                        secho(f"{prefix}└── ⚠️ [已達到最大顯示數量限制 {state['max_items']} 筆，停止展開]", fg=typer.colors.YELLOW)
                        state["limit_reached"] = True
                    return

                is_last = (index == len(items) - 1)
                connector = "└── " if is_last else "├── "

                if item.is_dir:
                    # 如果不是 files_only，就正常印出資料夾
                    if not files_only:
                        echo(f"{prefix}{connector}📁 {style(item.name, fg=typer.colors.BLUE, bold=True)}")
                        state["count"] += 1

                    # 判斷深度，決定是否繼續向下遞迴展開
                    if depth is None or current_depth < depth:
                        extension = "    " if is_last else "│   "
                        # 遞迴呼叫，累積前綴的視覺線條
                        walk_tree(item.path, prefix + extension, current_depth + 1)
                else:
                    # dirs_only 前面已過濾，走到這裡一定是檔案
                    # 將我們之前寫的 format_size 稍微調暗，讓視覺焦點保持在樹狀結構上
                    size_str = format_size(item.size) if hasattr(item, 'size') else ""
                    size_display = style(f" ({size_str})", fg=typer.colors.BRIGHT_BLACK)
                    
                    echo(f"{prefix}{connector}📄 {item.name}{size_display}")
                    state["count"] += 1

        # 啟啟動遞迴遍歷
        walk_tree(parsed_remote_path)

        echo("")
        if not state["limit_reached"]:
            secho(f"總計顯示: {state['count']} 個項目", fg=typer.colors.GREEN)

    except Exception as exc:
        render_error(
            "無法建立目錄樹。",
            cause=exc,
            next_steps=(
                "確認 Remote 路徑可讀取。",
                "若目錄很大，可設定 `--depth` 與 `--max-items` 限制展開範圍。",
            ),
        )
        raise typer.Exit(code=1) from exc

def find_items(
    remote_path: str = typer.Argument(..., help="要開始搜尋的遠端路徑 (例如: my_sp:/Shared Documents)"),
    name: str = typer.Option(None, "--name", "-n", help="檔案名稱 (支援萬用字元 *.xlsx。若無萬用字元則自動啟用模糊搜尋)"),
    fuzzy_threshold: int = typer.Option(70, "--fuzzy-threshold", help="模糊搜尋相似度門檻 (0-100，預設 70)"),
    item_type: str = typer.Option(None, "--type", "-t", help="篩選類型: file 或 folder"),
    size_gt: str = typer.Option(None, "--size-gt", help="檔案大小大於 (例如 10MB)"),
    size_lt: str = typer.Option(None, "--size-lt", help="檔案大小小於 (例如 1GB)"),
    modified_after: str = typer.Option(None, "--modified-after", help="最後修改時間晚於 (格式 YYYY-MM-DD)"),
    modified_before: str = typer.Option(None, "--modified-before", help="最後修改時間早於 (格式 YYYY-MM-DD)"),
    max_depth: int = typer.Option(None, "--max-depth", help="最大搜尋深度 (預設無限遞迴)")
):
    """
    強大的跨雲端條件搜尋工具 (基於純客戶端遞迴，100% 支援所有節點)
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    # 預先解析所有過濾條件，若格式錯誤會提早報錯，不用等連線後才爆
    try:
        bytes_gt = parse_size_to_bytes(size_gt) if size_gt else None
        bytes_lt = parse_size_to_bytes(size_lt) if size_lt else None
        date_after = parse_date_to_aware_datetime(modified_after) if modified_after else None
        date_before = parse_date_to_aware_datetime(modified_before) if modified_before else None
    except ValueError as exc:
        render_error(
            "搜尋條件格式無效。",
            cause=exc,
            next_steps=("執行 `drive-unix find --help` 查看大小與日期格式。",),
        )
        raise typer.Exit(code=1) from exc

    # 驗證 item_type
    if item_type and item_type not in ["file", "folder"]:
        render_error(
            "搜尋類型無效。",
            cause="--type 僅接受 `file` 或 `folder`。",
            next_steps=("例如：`--type file`。",),
        )
        raise typer.Exit(code=1)

    try:
        remote_name, parsed_remote_path = parse_remote_path(remote_path, config_manager.config.default_remote)
        storage = get_storage_provider(remote_name, config_manager)

        secho(f"🔍 開始在 [{remote_name}] {parsed_remote_path or '/'} 進行深度搜尋...", fg=typer.colors.CYAN, bold=True)
        echo("-" * 50)

        match_count = 0

        # 定義遞迴搜尋函式
        def recursive_search(current_path: str, current_depth: int = 1):
            nonlocal match_count

            # 若達到深度限制則停止
            if max_depth is not None and current_depth > max_depth:
                return

            try:
                # 這裡調用之前升級過、具備自動分頁防爆能力的 list_dir
                items = storage.list_dir(current_path)
            except Exception as e:
                secho(f"⚠️ 無法讀取目錄 {current_path}: {e}", fg=typer.colors.YELLOW)
                return

            for item in items:
                is_match = True

                # 1. 篩選類型 (Type)
                if item_type:
                    if item_type == "file" and item.is_dir:
                        is_match = False
                    elif item_type == "folder" and not item.is_dir:
                        is_match = False

                # 2. 篩選名稱 (支援萬用字元與中英文模糊搜尋)
                if is_match and name:
                    name_lower = name.lower()
                    item_name_lower = item.name.lower()
                    # 判斷是否包含 Linux 標準萬用字元
                    if '*' in name_lower or '?' in name_lower:
                        if not fnmatch.fnmatch(item.name.lower(), name.lower()):
                            is_match = False
                    else:
                        # 走 fuzzywuzzy 中英文模糊比對
                        # 使用 partial_ratio 進行子字串匹配 (例如搜 "報告" 能比中 "2026_年度報告_v2")
                        ratio = fuzz.partial_ratio(name_lower, item_name_lower)
                        # 若相似度低於門檻，則視為不匹配
                        if ratio < fuzzy_threshold:
                            is_match = False

                # 3. 篩選大小 (Size) - 僅對檔案有效
                if is_match and not item.is_dir:
                    if bytes_gt is not None and item.size <= bytes_gt:
                        is_match = False
                    if bytes_lt is not None and item.size >= bytes_lt:
                        is_match = False
                elif is_match and item.is_dir and (bytes_gt or bytes_lt):
                    # 如果使用者設定了大小條件，但目標是資料夾，通常我們就不算它 match
                    is_match = False

                # 4. 篩選時間 (Modified Date)
                if is_match and (date_after or date_before):
                    if item.modified_at:
                        if date_after and item.modified_at < date_after:
                            is_match = False
                        if date_before and item.modified_at > date_before:
                            is_match = False
                    else:
                        # 檔案若沒有時間屬性，在時間篩選時視為不符
                        is_match = False

                # 如果全部條件通過，立刻印出結果！
                if is_match:
                    match_count += 1
                    icon = "📁" if item.is_dir else "📄"
                    size_str = format_size(item.size) if not item.is_dir else "-"
                    time_str = format_time(item.modified_at.isoformat()) if item.modified_at else "未知時間"
                    
                    # 排版輸出
                    echo(f"{icon} {style(item.path.ljust(50), fg=typer.colors.GREEN)} | 大小: {size_str.ljust(10)} | 修改: {time_str}")

                # 如果是資料夾，遞迴深入
                if item.is_dir:
                    recursive_search(item.path, current_depth + 1)

        # 啟動搜尋引擎
        recursive_search(parsed_remote_path)

        echo("-" * 50)
        secho(f"🎯 搜尋完畢！共找到 {match_count} 個符合條件的項目。", fg=typer.colors.CYAN, bold=True)

    except Exception as exc:
        render_error(
            "遞迴搜尋失敗。",
            cause=exc,
            next_steps=(
                "確認 Remote 連線與起始路徑。",
                "執行 `drive-unix remote test <REMOTE>` 測試認證與讀取權限。",
            ),
        )
        raise typer.Exit(code=1) from exc

def search_api(
    remote_path: str = typer.Argument(..., help="搜尋的起始遠端路徑 (例如: my_sp:/Shared Documents)"),
    query: str = typer.Argument(..., help="搜尋關鍵字")
):
    """
    使用遠端原生 API 進行極速搜尋
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        remote_name, parsed_remote_path = parse_remote_path(remote_path, config_manager.config.default_remote)
        storage = get_storage_provider(remote_name, config_manager)
        
        secho(f"⚡ 啟動伺服器端原生搜尋: [{remote_name}] 關鍵字 '{query}' ...", fg=typer.colors.CYAN)
        
        try:
            items = storage.search(parsed_remote_path, query)
        except NotImplementedError as exc:
            render_error(
                "此 Provider 不支援伺服器端搜尋。",
                cause=exc,
                next_steps=("改用 `drive-unix find REMOTE:/path --name <pattern>` 進行客戶端搜尋。",),
            )
            raise typer.Exit(code=2) from exc
            
        if not items:
            secho("沒有找到符合條件的項目。", fg=typer.colors.YELLOW)
            return
            
        secho(f"\n✅ 搜尋完畢！找到 {len(items)} 個項目:\n", fg=typer.colors.GREEN)
        
        # 沿用我們先前寫好的排版美學
        for item in items:
            icon = "📁" if item.is_dir else "📄"
            size_str = format_size(item.size) if not item.is_dir else "-"
            time_str = format_time(item.modified_at.isoformat()) if item.modified_at else "未知時間"
            
            echo(f"{icon} {style(item.path.ljust(50), fg=typer.colors.GREEN)} | 大小: {size_str.ljust(10)} | 修改: {time_str}")

    except typer.Exit:
        raise
    except Exception as exc:
        render_error(
            "伺服器端搜尋失敗。",
            cause=exc,
            next_steps=(
                "確認 Remote 連線、搜尋權限與起始路徑。",
                "若 Provider 不支援原生搜尋，改用 `drive-unix find`。",
            ),
        )
        raise typer.Exit(code=1) from exc

def make_directory(
    remote_path: str = typer.Argument(..., help="要建立的資料夾路徑 (例如: my_sp:/Shared Documents/A/B)"),
    parents: bool = typer.Option(False, "--parents", "-p", help="自動建立不存在的父目錄 (類似 mkdir -p)")
):
    """
    在雲端建立新資料夾
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        remote_name, parsed_remote_path = parse_remote_path(remote_path, config_manager.config.default_remote)
        
        storage = get_storage_provider(remote_name, config_manager)
        success = storage.mkdir(parsed_remote_path, parents=parents)
        
        if success:
            secho(f"✅ 成功建立資料夾: [{remote_name}] {parsed_remote_path}", fg=typer.colors.GREEN)
            
    except Exception as exc:
        render_error(
            "建立資料夾失敗。",
            cause=exc,
            next_steps=(
                "確認父目錄存在；需要自動建立父目錄時使用 `--parents`。",
                "確認 Remote 寫入權限。",
            ),
        )
        raise typer.Exit(code=1) from exc

def remove(
    remote_path: str = typer.Argument(..., help="遠端檔案或資料夾路徑 (例如: my_sp:/Shared Documents/file.txt)"),
    permanent: bool = typer.Option(
        False,
        "--permanent",
        "-p",
        help="要求永久刪除；若 Provider 不支援回收桶，刪除本來就是永久的",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="強制刪除，不跳出確認提示")
):
    """
    刪除 Remote 上的檔案或資料夾
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        remote_name, parsed_remote_path = parse_remote_path(remote_path, config_manager.config.default_remote)
        storage = get_storage_provider(remote_name, config_manager)
        storage.validate_delete_request(permanent=permanent)

        if storage.delete_capability == DeleteCapability.PERMANENT_ONLY:
            action = "永久刪除（此 Provider 不支援回收桶，無法由 drive-unix 復原）"
        elif permanent:
            action = "永久刪除（無法由 drive-unix 復原）"
        else:
            action = "移至回收桶（可由 Provider 的回收機制復原）"

        # 防呆確認機制：文案必須反映 Provider 真正的刪除語意。
        if not force:
            remote_type = None
            if hasattr(config_manager, "get_remote"):
                try:
                    remote_type = config_manager.get_remote(remote_name).type
                except Exception:
                    pass
            if remote_type == "googlephotos":
                secho("💡 提示：Google Photos 僅支援自相簿移除關聯，照片實體仍會保留於個人相簿庫中。", fg=typer.colors.CYAN)
            secho(f"⚠️ 警告：你即將把 [{remote_name}] 的 {parsed_remote_path} {action}。", fg=typer.colors.YELLOW)
            if not typer.confirm("確定要繼續嗎？"):
                raise typer.Abort()

        success = storage.delete(parsed_remote_path, permanent=permanent)

        if success:
            secho("✅ 刪除成功！", fg=typer.colors.GREEN)
        else:
            secho("⚠️ 刪除成功 (目標檔案可能已經不存在)。", fg=typer.colors.YELLOW)

    except typer.Abort:
        secho("🛑 已取消刪除操作。", fg=typer.colors.YELLOW)
    except Exception as exc:
        render_error(
            "刪除操作失敗。",
            cause=exc,
            next_steps=(
                "確認 Remote 路徑存在且具備刪除權限。",
                "執行 `drive-unix remote test <REMOTE>` 確認連線；需要寫入測試時加 `--write`。",
            ),
        )
        raise typer.Exit(code=1) from exc

def stat_item(
    remote_path: str = typer.Argument(..., help="路徑 (例如: my_sp:/ 查節點，或 my_sp:/docs/A.pdf 查檔案)"),
    json_output: bool = typer.Option(False, "--json", help="輸出穩定 JSON，適合腳本使用"),
):
    """
    查看節點容量資訊，或檔案/資料夾的詳細屬性
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        remote_name, parsed_remote_path = parse_remote_path(remote_path, config_manager.config.default_remote)
        storage = get_storage_provider(remote_name, config_manager)
        
        info = storage.stat(parsed_remote_path)

        if json_output:
            echo(
                json.dumps(
                    {"remote": remote_name, "path": parsed_remote_path, **info},
                    ensure_ascii=False,
                    default=str,
                )
            )
            return
        
        echo("") # 排版空行
        
        # 針對遠端節點 (顯示硬碟容量)
        if info["type"] == "remote":
            secho(f"📊 遠端節點資訊: [{remote_name}]", fg=typer.colors.CYAN, bold=True)
            echo("-" * 40)
            
            total_str = format_size(info["total"]) if info["total"] != -1 else "未提供"
            used_str = format_size(info["used"]) if info["used"] != -1 else "未提供"
            
            # 避免除以零與負數
            usage_percent = 0
            if info["total"] > 0 and info["used"] >= 0:
                usage_percent = (info["used"] / info["total"] * 100)
                
            # 容量百分比顏色提醒
            percent_color = typer.colors.GREEN
            if usage_percent > 80: percent_color = typer.colors.YELLOW
            if usage_percent > 95: percent_color = typer.colors.RED
            
            echo(f"📁 對應文件庫: {info['name']}")
            echo(f"💿 總儲存空間: {total_str}")
            if usage_percent > 0:
                echo(f"📦 已用空間  : {used_str} ", nl=False)
                secho(f"({usage_percent:.1f}%)", fg=percent_color, bold=True)
            else:
                echo(f"📦 已用空間  : {used_str}")
            echo(f"🗂️ 檔案數量  : {info.get('filecount', -1)}")
            echo(f"📅 建立時間  : {format_time(info['created'])}")
            echo(f"⏱️ 最後修改  : {format_time(info['modified'])}")
            
        # 針對單一檔案或資料夾
        else:
            icon = "📁" if info["type"] == "folder" else "📄"
            item_type_str = "資料夾" if info["type"] == "folder" else "檔案"
            
            secho(f"{icon} {item_type_str}資訊: {info['name']}", fg=typer.colors.CYAN, bold=True)
            echo("-" * 40)
            echo(f"📍 遠端路徑: {parsed_remote_path}")
            echo(f"📏 大小    : {format_size(info['size'])}")
            echo(f"📅 建立時間: {format_time(info['created'])}")
            echo(f"⏱️ 最後修改: {format_time(info['modified'])}")
            
        echo("-" * 40)

    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "無法取得項目資訊。",
                cause=exc,
                next_steps=(
                    "確認 Remote 名稱與路徑。",
                    "執行 `drive-unix remote test <REMOTE>` 檢查認證與讀取權限。",
                ),
            )
        raise typer.Exit(code=1) from exc

def register(app: typer.Typer) -> None:
    app.command("ls")(ls)
    app.command("tree")(show_tree)
    app.command("find")(find_items)
    app.command("search")(search_api)
    app.command("mkdir")(make_directory)
    app.command("rm")(remove)
    app.command("stat")(stat_item)
