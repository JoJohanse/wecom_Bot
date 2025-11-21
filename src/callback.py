#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信回调
"""

import os
import logging
import random
import string
import base64
import requests
from flask import request, Response
from sqlalchemy import text
from utils.WXBizJsonMsgCrypt import WXBizJsonMsgCrypt
from utils.WXBizMsgCrypt import WXBizMsgCrypt
from Crypto.Cipher import AES
from chatBot import logger

# 导入环境配置
from dotenv import load_dotenv
load_dotenv()

prikey = os.environ.get('prikey', '')

# 辅助函数
def get_xml_wechat_crypt(if_bot = False):
    """获取企业微信加密工具实例"""
    token = os.getenv('Token', '')
    encoding_aes_key = os.getenv('EncodingAESKey', '')
    # 如果是机器人回调，corpid为空
    corpid = '' if if_bot else os.getenv('corpid', '')
    return WXBizMsgCrypt(token, encoding_aes_key, corpid)

def parse_message(json_content):
    """解析企业微信机器人JSON消息"""
    try:
        # 处理不同类型的输入
        if isinstance(json_content, bytes):
            json_data = json.loads(json_content.decode('utf-8'))
        elif isinstance(json_content, str):
            json_data = json.loads(json_content)
        else:
            logger.error(f"不支持的消息内容类型: {type(json_content)}")
            return None
            
        # logger.info(f"解析JSON消息: {json_data}")
        
        message_info = {
            'msgtype': json_data.get('msgtype', ''),
            'aibotid': json_data.get('aibotid', ''),
            'from_user': json_data.get('from', {}).get('userid', ''),
            'chatid': json_data.get('chatid', ''),
            'content': '',
            'msg_id': json_data.get('msgid', ''),
        }
        
        # 根据消息类型提取内容
        if message_info['msgtype'] == 'text':
            # 提取的内容去掉@机器人的部分，类似@test机器人 如何登录spd系统
            message_info['content'] = re.sub(r'@\w+\s*', '', json_data.get('text', {}).get('content', ''))
            logger.info(f"提取的文本内容: {message_info['content']}")
        elif message_info['msgtype'] == 'event':
            message_info['event'] = json_data.get('event', {})
        elif message_info['msgtype'] == 'stream':
            message_info['stream_id'] = json_data.get('stream', {}).get('id', '')
        elif message_info['msgtype'] == 'image':
            message_info['content'] = f"[图片消息]"
        elif message_info['msgtype'] == 'voice':
            message_info['content'] = f"[语音消息]"
        
        return message_info
            
    except Exception as e:
        logger.error(f"消息解析错误: {e}")
        return None
        
def wechat_callback():
    """企业微信回调接口"""
    # 获取加密工具
    wxcrypt = get_xml_wechat_crypt()
    
    if request.method == 'GET':
        # URL验证
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')
        logger.info(f"URL验证请求: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr}")
        ret, reply = wxcrypt.VerifyURL(msg_signature, timestamp, nonce, echostr)
        if ret == 0:
            logger.info("URL验证成功")
            return reply
        
        logger.error("URL验证失败")
        return 'URL验证失败', 403
    
    elif request.method == 'POST':
        # 处理消息
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        
        try:
            # 获取加密的消息数据
            encrypt_msg = request.data
            # logger.info(f"收到原始消息数据: {encrypt_msg[:200]}...")
            # logger.info(f"消息数据类型: {type(encrypt_msg)}")
            # logger.info(f"消息数据长度: {len(encrypt_msg)}")
            
            if not wxcrypt:
                logger.error("加密工具未初始化")
                return 'Encryption tool not initialized', 500
            
            ret, decrypted_msg = wxcrypt.DecryptMsg(encrypt_msg, msg_signature, timestamp, nonce)
            if ret != 0:
                logger.error(f"消息解密失败，错误码: {ret}")
                return 'Decryption failed', 400
            # logger.info(f"解密后的消息: {decrypted_msg}")
            # 其他消息类型暂不处理
            return decrypted_msg, 200
            
        except Exception as e:
            logger.error(f"处理消息异常: {str(e)}")
            return 'Internal server error', 500

