# -*- coding: utf-8 -*-
"""临时清理脚本：删除问答演示数据中被历史 curl 测试损坏的乱码记录（内容全为问号）。"""
import pymysql

conn = pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                       database="Ai_Farm_Manage", charset="utf8mb4")
cur = conn.cursor()
# 删除内容以连续问号开头的损坏 user 消息
cur.execute("SELECT id, session_id, role, LEFT(content, 10) FROM chat_message")
bad_msg_ids, bad_session_ids = [], set()
for mid, sid, role, head in cur.fetchall():
    if role == "user" and head and set(head) <= {"?"}:
        bad_msg_ids.append(mid)
        bad_session_ids.add(sid)
print("bad messages:", bad_msg_ids)
for mid in bad_msg_ids:
    cur.execute("DELETE FROM chat_message WHERE id=%s", (mid,))
# 删除标题全为问号的损坏会话（且会话已无有效消息）
for sid in bad_session_ids:
    cur.execute("SELECT COUNT(*) FROM chat_message WHERE session_id=%s", (sid,))
    if cur.fetchone()[0] == 0:
        cur.execute("DELETE FROM chat_session WHERE id=%s", (sid,))
        print("removed empty bad session:", sid)
conn.commit()
cur.execute("SELECT id, title FROM chat_session ORDER BY id")
print("sessions left:", cur.fetchall())
conn.close()
