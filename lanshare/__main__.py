"""コマンドラインからサーバを起動する。

    python -m lanshare                     # ./shared を共有、PINは自動生成
    python -m lanshare -d D:\\共有 -p 8080  # フォルダとポートを指定
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auth import generate_pin
from .config import DEFAULT_PORT, DEFAULT_ROOT, ServerConfig
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lanshare",
        description="ローカルネットワーク内でPCとスマートフォンの間でファイルをやり取りするサーバ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  python -m lanshare\n"
            "  python -m lanshare --dir \"D:\\共有\" --port 8080\n"
            "  python -m lanshare --on-conflict backup\n"
        ),
    )
    parser.add_argument("-d", "--dir", default=DEFAULT_ROOT, help="共有フォルダ(既定: ./shared)")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"待ち受けポート(既定: {DEFAULT_PORT})")
    parser.add_argument("--host", default="0.0.0.0", help="待ち受けアドレス(既定: 0.0.0.0=全てのLAN側IP)")
    parser.add_argument("--pin", help="PINを固定する(既定: 起動ごとに6桁を自動生成)")
    parser.add_argument("--no-auth", action="store_true", help="PIN認証を無効にする(信頼できるLANのみ)")
    parser.add_argument("--allow-any-client", action="store_true",
                        help="プライベートIP以外からの接続も許可する(通常は不要)")
    parser.add_argument("--on-conflict", choices=["rename", "backup"], default="rename",
                        help="同名ファイルの扱い。rename=別名保存(既定) / backup=_backup へ日時つきで退避して上書き")
    parser.add_argument("--hard-delete", action="store_true",
                        help="削除時にゴミ箱(_trash)へ退避せず即座に消す(復元不可)")
    parser.add_argument("--session-ttl", type=int, default=12, help="ログインの有効時間(時間、既定: 12)")
    parser.add_argument("--no-qr", action="store_true", help="起動時にQRコードを表示しない")
    parser.add_argument("--open", action="store_true", help="起動後にPCのブラウザで開く")
    parser.add_argument("-q", "--quiet", action="store_true", help="アクセスログを表示しない")
    return parser


def main(argv: list[str] | None = None) -> int:
    # 日本語を出せないコンソール(英語版Windowsなど)でも落ちないようにする
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)

    if args.pin and not args.pin.isdigit():
        print("エラー: --pin は数字で指定してください", file=sys.stderr)
        return 2

    config = ServerConfig(
        root=Path(args.dir),
        host=args.host,
        port=args.port,
        pin=None if args.no_auth else (args.pin or generate_pin()),
        require_auth=not args.no_auth,
        allow_any_client=args.allow_any_client,
        on_conflict=args.on_conflict,
        hard_delete=args.hard_delete,
        session_ttl=max(1, args.session_ttl) * 3600,
        quiet=args.quiet,
    )

    if args.hard_delete:
        print("警告: --hard-delete が有効です。UIから削除したファイルはPCから即座に消え、"
              "復元できません(既定では _trash/ に退避します)。", file=sys.stderr)
    if args.no_auth:
        print("警告: PIN認証が無効です。同じLAN内の誰でも共有フォルダを読み書きできます。",
              file=sys.stderr)

    try:
        serve(config, show_qr=not args.no_qr, open_browser=args.open)
    except OSError as error:
        print(f"エラー: 起動できませんでした ({error})", file=sys.stderr)
        if getattr(error, "errno", None) in (98, 10048):
            print(f"ポート {args.port} は使用中です。--port で別の番号を指定してください。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
