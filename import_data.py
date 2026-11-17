import os
import sqlite3
import sys
from lxml import etree

DB = os.path.join(os.path.dirname(__file__), "port_ops.db")
FIELDS = ["排柜单号","目的仓","目的仓物流区域","目的仓国家","ATA日期","目的港/站卸柜日期",
          "货代","港前拖车行","卸货港","卸货码头","目的港码头","码头","Terminal","目的地","船公司","实际船名","实际航次","ETA日期",
          "箱号","MB/L No.","港后拖车行","LFD","海关放行时间","清关完成时间",
          "进口实际提箱时间","约仓时间","实际送仓时间","实际到海外仓日期",
          "实际还柜日期","预计还柜时间","进口查验开始日期","进口查验完成日期","港后内部备注"]

def load(path):
    # Import into a temporary DB first; never destroy the existing database on failure.
    temp_db = DB + ".importing"
    if os.path.exists(temp_db):
        os.remove(temp_db)
    conn = sqlite3.connect(temp_db)
    try:
        columns = ",".join('"' + f + '" TEXT' for f in FIELDS)
        conn.execute("CREATE TABLE containers (id INTEGER PRIMARY KEY," + columns + ")")
        cols = None
        batch = []
        count = 0
        insert = "INSERT INTO containers (" + ",".join('"' + f + '"' for f in FIELDS) + ") VALUES (" + ",".join("?" for _ in FIELDS) + ")"
        for _, el in etree.iterparse(path, events=("end",), tag="tr", html=True):
            cells = el.xpath("./th|./td")
            if cols is None:
                cols = ["".join(c.itertext()).strip() for c in cells]
                el.clear()
                continue
            if len(cells) == len(cols):
                values = ["".join(c.itertext()).strip() for c in cells]
                row = dict(zip(cols, values))
                if row.get("目的仓国家", "").upper() in ("AMERICA","USA","UNITED STATES","美国","US"):
                    batch.append(tuple(row.get(f, "") for f in FIELDS))
                    count += 1
            if len(batch) >= 500:
                conn.executemany(insert, batch)
                batch = []
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
        if batch:
            conn.executemany(insert, batch)
        conn.execute('CREATE INDEX idx_region ON containers("目的仓物流区域")')
        conn.commit()
        if not count:
            raise ValueError("未发现美国目的仓记录，请检查源文件格式及字段")
    except Exception:
        conn.close()
        os.remove(temp_db)
        raise
    conn.close()
    os.replace(temp_db, DB)
    print("Imported US records:", count)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python import_data.py source.xls")
    load(sys.argv[1])
