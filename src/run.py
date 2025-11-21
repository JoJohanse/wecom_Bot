import os
import subprocess
import signal
from flask import Flask, Blueprint
from chatBot import chatBot_callback
from callback import wechat_callback
from WeCom_Bot import Bot,logger
from datetime import datetime
from flask_apscheduler import APScheduler
from sqlalchemy import text


# 创建Flask应用实例
app = Flask(__name__)
scheduler = APScheduler()

# 创建蓝图并注册路由
wechat = Blueprint('wechat', __name__)
wechat.route('/callback', methods=['GET', 'POST'])(wechat_callback)
wechat.route('/callback/chatBot', methods=['GET', 'POST'])(chatBot_callback)
app.register_blueprint(wechat, url_prefix='/wechat')

# # 定时执行
# @scheduler.task('cron', id='summarize_schedule', hour=11, minute=55, timezone='Asia/Shanghai')
# def summarize_schedule():
#     logger.info(f"定时总结开始,当前时间为: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
#     db = Bot.sql_db
#     # 查询数据
#     with db.connect() as con:
#         chatidlist = con.execute(text("SELECT DISTINCT roomid FROM wecom_messages")).scalars().all()
#     for chatid in chatidlist:
#         # # 假设存有chatid对应群聊的webhook_key
#         # webhook_key = con.execute(text("SELECT webhook_key FROM wecom_chatrooms WHERE roomid = :roomid")).scalar()
#         webhook_key = os.getenv("webhook_key")
#         summary_content = Bot.SumarizeChat_Webhook(chatid)
#         try:
#             if summary_content:
#                 # 调用企业微信webhook发送总结消息
#                 url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + webhook_key
#                 payload ={
#                     "msgtype": "text",
#                     "text": {"content": summary_content}
#                 }
#                 response = requests.post(url, json=payload)
#                 if response.status_code != 200:
#                     logger.error(f"发送总结消息到群聊 {chatid} 失败, 状态码: {response.status_code}, 响应: {response.text}")
#         except Exception as e:
#             logger.error(f"处理群聊 {chatid} 总结时出错: {e}")
#     logger.info(f"已完成{len(chatidlist)}个群聊的总结,当前时间为: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# 定时清理
@scheduler.task('cron', id='clean_schedule', hour=3, minute=0, timezone='Asia/Shanghai')
def clean_schedule():
    logger.info(f"定时清理开始，当前日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    db = Bot.sql_db
    # 定义时间戳阈值，计算7天前的毫秒时间戳
    time_threshold = "EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) * 1000 - 7 * 24 * 60 * 60 * 1000"
    
    with db.connect() as con:
        count_result = con.execute(text(f"SELECT COUNT(*) FROM wecom_messages WHERE wecom_messages.msgtime < ({time_threshold})"))
        pending_delete_count = count_result.scalar()
        if pending_delete_count > 0:
            logger.info(f"将清理 {pending_delete_count} 条7天前的记录")
            delete_result = con.execute(text(f"DELETE FROM wecom_messages WHERE wecom_messages.msgtime < ({time_threshold}) RETURNING msgid"))
            deleted_count = len(delete_result.fetchall())
            con.commit()  # 提交事务
            logger.info(f"成功删除了 {deleted_count} 条7天前的记录")
        else:
            con.commit()  # 提交事务
            logger.info("没有需要清理的记录")
    logger.info(f"定时清理完成，当前日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

save_process = None

def start_and_manage_services():
    """
    启动和管理所有服务，包括子进程启动和信号处理
    """
    global save_process
    
    def _start_save_process():
        save_chat_path = os.path.join(os.path.dirname(__file__), 'save_chat.py')
        try:
            process = subprocess.Popen(
                ['python', save_chat_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            logger.info(f"已启动save_chat.py，进程ID: {process.pid}")
            return process
        except Exception as e:
            logger.error(f"启动save_chat.py失败: {str(e)}")
            return None
    
    # 关闭所有服务
    def _shutdown_services():
        # 关闭调度器（先检查是否正在运行）
        try:
            if scheduler.running:
                scheduler.shutdown()    
                logger.info("调度器已关闭")
            else:
                logger.info("调度器未运行，无需关闭")
        except Exception as e:
            logger.error(f"关闭调度器时出错: {str(e)}")
        # 关闭子进程
        if save_process and save_process.poll() is None:
            logger.info(f"关闭会话存档进程 (PID: {save_process.pid})")
            try:
                save_process.terminate()
                save_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 超时则强制终止
                logger.warning("会话存档进程终止超时，强制终止")
                save_process.kill()
    
    # 定义信号处理函数
    def _signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，准备关闭服务")
        _shutdown_services()
        exit(0)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    
    # 启动子进程
    save_process = _start_save_process()
    
    # 启动调度器
    scheduler.init_app(app)
    scheduler.start()
    logger.info("调度器已启动")
    try:
        app.run(debug=False, host='0.0.0.0', port=int(os.getenv('port', 3456)))
    except (KeyboardInterrupt, SystemExit):
        _shutdown_services()
        logger.info("服务已关闭")

if __name__ == '__main__':
    logger.info("服务启动中...")
    logger.info(f"当前时间为: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    start_and_manage_services()
    
    ### nohup python run.py > wecom_Bot/log/server.log 2>&1 &