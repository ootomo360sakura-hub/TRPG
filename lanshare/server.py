"""サーバの起動処理。"""

from __future__ import annotations

import socket
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from . import qr
from .config import ServerConfig
from .handler import AppContext, make_handler


class LanShareServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def server_bind(self) -> None:
        # 大きなファイルの転送でスループットを落とさないため Nagle を無効化する
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        super().server_bind()


def create_server(config: ServerConfig) -> tuple[LanShareServer, AppContext]:
    context = AppContext(config)
    server = LanShareServer((config.host, config.port), make_handler(context))
    return server, context


def banner(context: AppContext, show_qr: bool = True) -> str:
    config = context.config
    lines = [
        "",
        "=" * 56,
        "  LANファイル共有サーバを起動しました",
        "=" * 56,
        f"  共有フォルダ : {context.store.root}",
        "  接続先URL    : " + ("\n                 ".join(context.share_urls())),
    ]
    if context.auth.enabled:
        lines.append(f"  PIN          : {config.pin}   ← iPhoneでURLを手入力したときに使う番号")
        if config.trust_local:
            lines.append("                 (このPCのブラウザからはPIN不要。QRで開いたiPhoneも入力不要)")
        else:
            lines.append("                 (--require-local-pin 指定のため、このPCでもPINを求めます)")
    else:
        lines.append("  PIN          : なし(--no-auth で認証を無効化しています)")
    lines += [
        "  同名ファイル : " + ("_backup/ に日時つきで退避してから上書き"
                               if config.on_conflict == "backup" else "別名(連番)で保存"),
        "  削除の扱い   : " + ("即時削除(復元不可)" if config.hard_delete
                               else "_trash/日時/ へ移動(PC側で復元可能)"),
        "-" * 56,
        "  1) PCのブラウザで上のURLを開くとセットアップ画面(QR表示)になります",
        "  2) iPhoneのカメラで下のQRを読み取るとSafariで接続します",
        "  3) 接続を検知するとPCの画面は自動でファイル転送画面に切り替わります",
        "  終了: Ctrl+C",
        "=" * 56,
    ]
    if show_qr:
        try:
            lines.append(qr.make(context.qr_url(with_pin=True), "M").to_ascii(border=2))
        except qr.QRError:
            pass
    return "\n".join(lines)


def serve(config: ServerConfig, show_qr: bool = True, open_browser: bool = False) -> None:
    """サーバを起動し、Ctrl+Cまで動かし続ける。"""
    server, context = create_server(config)
    print(banner(context, show_qr), flush=True)

    if open_browser:
        # PC側はPIN入力を省いてセットアップ(QR)画面をそのまま開く
        local = f"http://127.0.0.1:{config.port}/"
        if context.auth.enabled and config.pin:
            local += f"?pin={config.pin}"
        threading.Timer(0.7, lambda: webbrowser.open(local)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。", flush=True)
    finally:
        server.shutdown()
        server.server_close()
