#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信会话存档保存服务
利用企微SDK,从数据库获取企业微信会话存档，保存到本地文件
"""
import os
import json
import base64
import time
import requests
import sqlalchemy
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from sqlalchemy import text
from chatBot import logger
from utils.WeComFinanceSdk_python import WeWorkFinanceSdk
from dotenv import load_dotenv
load_dotenv()


class WecomChatArchiver:
    """
    企业微信会话存档服务类
    用于从企业微信API获取会话数据并保存到本地和数据库
    """
    
    def __init__(self, corp_id=None, corp_key=None, prikey_path=None, db_url=None):
        """
        初始化企业微信会话存档服务
        
        Args:
            corp_id: 企业ID，默认为None时从环境变量获取
            corp_key: 企业密钥，默认为None时从环境变量获取
            prikey_path: 私钥文件路径，默认为None时从环境变量获取
            db_url: 数据库连接URL，默认为None时从环境变量获取
        """
        self.corp_id = corp_id or os.environ.get('corpid', '')
        self.corp_key = corp_key or os.environ.get('secret', '')
        self.prikey_path = prikey_path or os.environ.get('prikey_path', '')
        self.db_url = db_url or os.getenv("db_url")
        
        # 处理相对路径 - 将相对路径转换为绝对路径
        if self.prikey_path and not os.path.isabs(self.prikey_path):
            # 获取项目根目录（假设save_chat.py在src目录下）
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # 将相对路径转换为绝对路径
            self.prikey_path = os.path.join(project_root, self.prikey_path)
        self.access_token = self._get_access_token()
        
        # 初始化数据库连接
        self.sql_db = sqlalchemy.create_engine(self.db_url)
        
        # 初始化SDK和相关变量
        self.sdk = None
        self.has_prikey = False
        self.cipher = None
        
    def initialize_sdk(self):
        """
        初始化企业微信SDK实例
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            self.sdk = WeWorkFinanceSdk.WeWorkFinanceSdk(self.corp_id, self.corp_key)
            
            if os.path.exists(self.prikey_path):
                with open(self.prikey_path) as pk_file:
                    privatekey = pk_file.read()
                # 初始化RSA
                rsakey = RSA.importKey(privatekey)
                self.cipher = PKCS1_v1_5.new(rsakey)
                self.has_prikey = True
            
            return True
        except Exception as e:
            logger.error(f"初始化SDK时出错: {e}")
            return False
    
    def process_message_by_type(self, data_details):
        """
        根据消息类型处理消息数据
        
        Args:
            data_details: 解密后的消息详情
        
        Returns:
            dict: 处理结果，包含状态和相关信息
        """
        try:
            msgtype = data_details.get('msgtype')
            if msgtype is None:
                return {"status": "skipped", "reason": "消息类型为空"}
            
            elif msgtype == 'text':
                content = data_details.get("text", {}).get("content", "")
                print(f'Text: {content}')
                return {"status": "success", "type": "text", "content": content}
            
            elif msgtype == 'file':
                file_info = data_details.get("file", {})
                fileid = file_info.get('sdkfileid')
                filename = file_info.get('filename')
                filelen = file_info.get('filesize')
                md5sum = file_info.get('md5sum')
                
                file_content, length = self.sdk.pull_media_file(file_id=fileid)
                if len(file_content) == filelen:
                    with open(f'./{filename}', 'wb') as dstf:
                        dstf.write(file_content)
                    return {"status": "success", "type": "file", "filename": filename}
                else:
                    raise Exception(f"文件下载失败: 大小不匹配")
            
            elif msgtype == 'image':
                image_info = data_details.get("image", {})
                fileid = image_info.get('sdkfileid')
                filesize = image_info.get('filesize')
                md5sum = image_info.get('md5sum')
                
                # 使用md5sum作为文件名，避免重复
                filename = f"image_{md5sum}.jpg"
                image_content, length = self.sdk.pull_media_file(file_id=fileid)
                
                if len(image_content) == filesize:
                    with open(f'./{filename}', 'wb') as dstf:
                        dstf.write(image_content)
                    print(f"图片已保存: {filename}")
                    return {"status": "success", "type": "image", "filename": filename}
                else:
                    raise Exception(f"图片下载失败: 实际大小{len(image_content)}与期望大小{filesize}不符")
            
            else:
                return {"status": "unsupported", "type": msgtype}
                
        except Exception as e:
            print(f"处理消息时出错: {e}")
            return {"status": "error", "error": str(e)}
    
    def _get_message_content(self, data_details):
        """
        获取合并后的消息内容
        将除基本字段外的所有内容合并成一个JSON对象
        
        Args:
            data_details: 解密后的消息详情
            msgtype: 消息类型
        
        Returns:
            dict: 合并后的消息内容
        """
        base_fields = ['msgid', 'action', 'from', 'tolist', 'roomid', 'msgtime', 'msgtype']
        # 创建一个新字典，包含非基本字段
        content = {}
        for key, value in data_details.items():
            if key not in base_fields:
                content[key] = value
        
        return content
    
    def _get_access_token(self):
        """
        获取企微后台接口的access_token
        
        Returns:
            str: 企业微信的access_token
        """
        try:
            response = requests.get(
                f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corp_id}&corpsecret={self.corp_key}"
            )
            response.raise_for_status()
            data = response.json()
            return data.get("access_token")
        except requests.RequestException as e:
            logger.error(f"获取access_token时出错: {e}")
            return None
    
    def _get_chat_name(self, roomid):
        """
        根据群聊roomid获取群聊名称
        
        Args:
            roomid: 群聊roomid
        
        Returns:
            str: 群聊名称
            bool: 是否成功
        """
        try:
            access_token = self.access_token
            response = requests.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/msgaudit/groupchat/get?access_token={access_token}",
                json={"roomid": roomid}
            )
            response.raise_for_status()
            data = response.json()
            return data.get("roomname"), True
        except requests.RequestException as e:
            logger.error(f"获取群聊名称时出错: {e}")
            # 尝试获取access_token后重试
            access_token = self._get_access_token()
            if access_token:
                response = requests.post(
                    f"https://qyapi.weixin.qq.com/cgi-bin/msgaudit/groupchat/get?access_token={access_token}",
                    json={"roomid": roomid}
                )
                response.raise_for_status()
                data = response.json()
                return data.get("roomname"), True
            else:
                return "", False
                
    def save_to_database(self, msgid, action, from_userid, tolist, roomid, chat_name, msgtime, msgtype, content):
        """
        将对话内容保存到数据库
        
        Args:
            msgid: 消息id，消息的唯一标识
            action: 消息动作，send/recall/switch
            from_userid: 消息发送方id
            tolist: 消息接收方列表,text[]
            roomid: 群聊消息的群id
            msgtime: 消息发送时间戳
            msgtype: 消息类型
            content: 消息内容
        
        Returns:
            bool: 保存是否成功
        """
        try:
            content_json = json.dumps(content) if isinstance(content, dict) else content
            tlist = tolist if isinstance(tolist, list) else []
            
            with self.sql_db.connect() as con:
                with con.begin():
                    con.execute(
                        text("INSERT INTO wecom_messages (msgid, action, \"from\", tolist, roomid, chat_name, msgtime, msgtype, content) VALUES (:msgid, :action, :from_userid, :tolist, :roomid, :chat_name, :msgtime, :msgtype, :content)"),
                        {
                            "msgid": msgid,
                            "action": action,
                            "from_userid": from_userid,
                            "tolist": tlist,
                            "roomid": roomid,
                            "chat_name": chat_name,
                            "msgtime": msgtime,
                            "msgtype": msgtype,
                            "content": content_json
                        }
                    )
            return True
        except Exception as e:
            logger.error(f"保存到数据库时出错: {str(e)}")
            return False
    
    def is_message_exists(self, msgid, msgtype):
        """
        检查消息是否已存在于数据库中
        
        Args:
            msgid: 消息ID
            msgtype: 消息类型
        
        Returns:
            bool: 消息是否存在
        """
        try:
            with self.sql_db.connect() as con:
                result = con.execute(
                    text("SELECT 1 FROM wecom_messages WHERE msgid = :msgid AND msgtype = :msgtype"), 
                    {"msgid": msgid, "msgtype": msgtype}
                ).fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"检查消息是否存在时出错: {str(e)}")
            return False
    
    def process_chat_data(self, chat_data):
        """
        处理单条聊天数据
        
        Args:
            chat_data: 从API获取的单条聊天数据
        
        Returns:
            bool: 处理是否成功
        """
        if not self.has_prikey:
            return False

        try:
            pubkey_ver = chat_data.get('publickey_ver')
            rdkey_str = chat_data.get("encrypt_random_key")
            rdkey_decoded = base64.b64decode(rdkey_str)
            
            # 解密random key
            encrypt_key = str(bytes.decode(self.cipher.decrypt(rdkey_decoded, None)))
            if encrypt_key is None or len(encrypt_key) == 0:
                logger.error(f'解密失败，请检查私钥/密钥配置')
                return False
            
            # 解密消息内容
            encrypt_msg = chat_data.get("encrypt_chat_msg")
            byte_details, length = self.sdk.decrypt_data(encrypt_key, encrypt_msg)
            data_details = json.loads(byte_details)
            
            # 检查消息是否已存在
            msgid = data_details.get('msgid')
            msgtype = data_details.get('msgtype')
            
            if self.is_message_exists(msgid, msgtype):
                return True
            
            # 获取消息内容
            content = self._get_message_content(data_details)
            roomid = data_details.get('roomid')
            from_userid = data_details.get('from')
            # 根据群聊roomid获取群聊名称，若roomid为空则以from_userid为群聊名称
            if roomid:
                chat_name, _ = self._get_chat_name(roomid)
            else:
                chat_name = from_userid
             # 保存消息到数据库
            self.save_to_database(
                msgid=msgid,
                action=data_details.get('action'),
                from_userid=from_userid,
                tolist=data_details.get('tolist'),
                roomid=roomid,
                chat_name=chat_name,
                msgtime=data_details.get('msgtime'),
                msgtype=msgtype,
                content=content
            )   
            return True
            
        except Exception as e:
            # 私钥/公钥不匹配
            logger.error(f'解密失败，当前密钥版本: {pubkey_ver}, 错误: {str(e)}')
            return False
    
    def run(self, start_seq=0, record_limit=50, sleep_time=1):
        """
        运行主循环，持续获取并处理聊天数据
        
        Args:
            start_seq: 起始序列号
            record_limit: 每次获取的记录数量
            sleep_time: 每次循环后的等待时间(秒)
        """
        try:
            if not self.initialize_sdk():
                raise Exception("SDK初始化失败")
            
            current_seq = start_seq
            logger.info("企业微信会话存档服务已启动...")
            
            while True:
                # 获取聊天数据
                chat_data, length = self.sdk.get_chat_data(seq=current_seq, limit=record_limit)
                if chat_data is None:
                    logger.error(f"获取聊天数据失败")
                    continue
                ret_data = json.loads(chat_data)
                if ret_data.get("errcode") != 0:
                    logger.error(f"调用接口失败:{ret_data}")
                    continue
                origin_data_list = ret_data.get("chatdata")
                if len(origin_data_list) <= 0:
                    time.sleep(sleep_time)
                    continue
                # 获取最新的seq，用于下次请求
                current_seq = max([p.get('seq') for p in origin_data_list])

                for chat_data in origin_data_list:
                    self.process_chat_data(chat_data)
                # 一分钟内不得超过4000次调用，当前设置3000
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("服务已停止")
        except Exception as e:
            logger.error(f"Error: {e}")
        finally:
            # 清理SDK资源
            if self.sdk:
                self.sdk.destroy_sdk()
                logger.info("SDK已回收")


if __name__ == "__main__":
    # 创建并运行企业微信会话存档服务
    archiver = WecomChatArchiver()
    archiver.run()

