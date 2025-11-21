import requests
import json
import os
import time
import sqlalchemy
from datetime import datetime
from logging import handlers, getLogger,Formatter,INFO
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()
# 配置日志记录到文件
logger = getLogger('WeComBot')
logger.setLevel(INFO)
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# 获取项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 使用相对路径
log_file_path = os.path.join(project_root, 'log/WeComBot.log')
log_dir = os.path.dirname(log_file_path)
os.makedirs(log_dir, exist_ok=True)

handler = handlers.RotatingFileHandler(
    filename=log_file_path,
    maxBytes=1024*1024*20,  # 最多存储20MB日志
    backupCount=5,
    encoding='utf-8'
)

# 设置日志格式
formatter = Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class Wecom_Bot:
    def __init__(self, api_key="",base_url= os.getenv('dify_url'),db_url=os.getenv('db_url')):
        """
        初始化企业微信机器人
        
        Args:
            api_key (str): dify服务的API密钥
        """
        self.api_key = api_key
        self.base_url = base_url
        self.db_url = db_url
        self.sql_db = sqlalchemy.create_engine(self.db_url)
    
    def Rag_Query(self, query,stream, stream_id="",debug=False,full_response = [],user_id=""):
        """
        处理用户查询传给Dify服务生成回答 - 支持流式输出
        
        Args:
            query (str): 用户查询的问题
            debug (bool): 是否打印调试信息
            stream (callable, optional): 流式输出回调函数，接收每个chunk的内容
            stream_id (str): 流式输出ID，用于标识不同的流式输出请求
            full_response (list): 用于存储响应内容的列表
            
        Returns:
            str: 生成的完整回答
        """
        data_template = {
            "inputs": {
                "intention": "RAG"
            },
            "query": query,
            "response_mode": "streaming",
            "conversation_id": "",
            "user": user_id
        }
        try:
            start_time = time.time()
            response = requests.post(
                f"{self.base_url}/chat-messages?user={user_id}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=data_template,
                stream=True
            )
            if response.status_code == 200:
                for chunk in response.iter_lines():
                    if chunk:
                        try:
                            chunk = chunk.decode('utf-8')
                            if chunk.startswith("data: "):
                                chunk = chunk.replace("data: ", "")
                            if debug:
                                logger.info(f"Raw chunk: {chunk}")

                            json_chunk = json.loads(chunk)
                            if json_chunk.get('event') == 'message':
                                chunk_str = json_chunk.get('answer', '')
                                if chunk_str:
                                    # 将内容添加到完整响应中
                                    full_response.append(chunk_str)
                                    stream(stream_id,chunk_str)
                        except json.JSONDecodeError as e:
                            if debug:
                                logger.error(f"JSON decode error: {e}, chunk: {chunk}")
                        except Exception as e:
                            if debug:
                                logger.error(f"Error processing chunk: {e}")
                full_response_str = ''.join(full_response)
                logger.info(f"回答结束: 响应长度={len(full_response_str)}, 耗时: {(time.time() - start_time):.2f}秒")
            return full_response_str
        except Exception as e:
            logger.error(f"查询工作流调用错误: {str(e)}")
            # 发生错误时返回默认消息
            error_message = "查询工作流调用错误"  
            stream(stream_id, error_message)
            return error_message
        
    def SummarizeChat(self,chat_name,stream,stream_id,full_response = [],useid = False,user_id="",debug=False):
        """
        对某一聊天群的对话内容进行总结，提取关键信息。
        
        Args:
            chat_name (str): 聊天群名称,单聊则为用户id
            stream (callable, optional): 流式输出回调函数，接收每个chunk的内容
            stream_id (str): 流式输出ID，用于标识不同的流式输出请求
            full_response (list): 用于存储响应内容的列表
            useid (bool): 是否使用用户id作为聊天群名称,默认False
            user_id (str): 用户id
        
        Returns:
            str: 生成的总结内容
        """
        #查表获取会话内容
        if useid: # 传进来的是群聊id
            if debug:
                logger.info(f"传入群聊id:{chat_name}")
            with self.sql_db.connect() as con:
                records = con.execute(
                    text("SELECT content,msgtime FROM wecom_messages WHERE roomid = :chat_name"),
                    {"chat_name": chat_name}
                ).fetchall()

        if not useid: # 传进来的是群聊名称
            if debug:
                logger.info(f"传入群聊名称:{chat_name}")
            with self.sql_db.connect() as con:
                records = con.execute(
                    text("SELECT content,msgtime FROM wecom_messages WHERE chat_name = :chat_name"),
                    {"chat_name": chat_name}
                ).fetchall()

        content_list = [item[0] for item in records]
        timestamp_list = [item[1] for item in records]
        # 转换时间格式
        timestamp_list = [datetime.fromtimestamp(int(timestamp / 1000)).strftime("%Y-%m-%d %H:%M:%S") for timestamp in timestamp_list]
        time_range = f"时间范围: {timestamp_list[0]} 至 {timestamp_list[-1]}\n"
        stream(stream_id,time_range)
        message_count = 0
        for i, message in enumerate(content_list):
            message_prompt += f"聊天记录{i+1}\n{message}\n\n" 
            message_count += 1
        summary_template = {
            "inputs": {
                "intention": "Summarize"
            },
            "query": message_prompt,
            "response_mode": "streaming",
            "conversation_id": "",
            "user": user_id
        }
        # 调用模型生成总结
        logger.info("群聊消息智能汇总中...")
        try:
            start_time = time.time()
            response = requests.post(
                f"{self.base_url}/chat-messages?user={user_id}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=summary_template,
                stream=True
            )
            # 处理流式响应
            for chunk in response.iter_lines():
                if chunk:
                    try:
                        chunk = chunk.decode('utf-8')
                        if chunk.startswith("data: "):
                            chunk = chunk.replace("data: ", "")
                        if debug:
                            logger.info(f"Raw chunk: {chunk}")

                        json_chunk = json.loads(chunk)
                        if json_chunk.get('event') == 'message':
                            chunk_str = json_chunk.get('answer', '')
                            if chunk_str:
                                # 将内容添加到完整响应中
                                full_response.append(chunk_str)
                                stream(stream_id,chunk_str)
                    except json.JSONDecodeError as e:
                        if debug:
                            logger.error(f"JSON decode error: {e}, chunk: {chunk}")
                    except Exception as e:
                        if debug:
                            logger.error(f"Error processing chunk: {e}")
            full_response_str = f"{time_range}{''.join(full_response).lstrip('\n')}"
            logger.info(f"回答结束: 响应长度={len(full_response_str)}, 耗时: {(time.time() - start_time):.2f}秒")
            return full_response_str
        except Exception as e:
            logger.error(f"查询工作流调用错误: {str(e)}")
            # 发生错误时返回默认消息
            error_message = "查询工作流调用错误"  
            stream(stream_id, error_message)
            return error_message
        

Bot = Wecom_Bot(
    api_key=os.getenv("dify_key")
    )      
# 示例用法
if __name__ == "__main__":
    query = input("请输入查询内容: ")
    response = Bot.Rag_Query(query, stream=None, stream_id="", debug=False, full_response=[], user_id="abc-123")
    # response = Bot.Summarize_Query(query, stream=None, stream_id="", debug=False, full_response=[], user_id="abc-123")
    print(response)