"""把建好的資料夾打成發佈用的 zip，並附上 SHA-256。

    python packaging/package_release.py <建置出的資料夾> <版本> <輸出目錄>

zip 叫 cc-quota-tracker-<版本>-win64.zip，解壓縮後得到一個 cc-quota-tracker 資料夾（兩個 exe 與 _internal 都在裡面）；
旁邊的 .zip.sha256 是 `<雜湊>  <檔名>` 一行，與 sha256sum 的格式相同。"""
import hashlib
import shutil
import sys
from pathlib import Path


REQUIRED = ("cc-quota-tracker.exe", "cc-quota-tracker-cli.exe")  # 開機自動啟動登錄視窗 exe、README 教人用命令列 exe


def package(folder: Path, version: str, out_dir: Path) -> Path:
    missing = [name for name in REQUIRED if not (folder / name).is_file()]
    if missing:
        raise SystemExit(f"建置出的資料夾 {folder} 缺少 {', '.join(missing)}，不打包")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"cc-quota-tracker-{version}-win64.zip"
    base = out_dir / name[:-len(".zip")]
    # root_dir 是資料夾的上一層、base_dir 是資料夾本身：解壓縮後最外層就是那個資料夾，不會把檔案散在目前目錄
    archive = Path(shutil.make_archive(str(base), "zip", root_dir=folder.parent, base_dir=folder.name))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    # newline="\n"：在 Windows 上預設會寫成 \r\n，sha256sum -c 讀得到的檔名尾巴會多一個 \r
    with open(out_dir / f"{name}.sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{digest}  {name}\n")
    return archive


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    print(package(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])))
