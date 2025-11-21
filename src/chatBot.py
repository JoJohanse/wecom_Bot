#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信机器人接口服务
接收企业微信消息，调用大模型，返回响应
"""

import json
import time
import traceback
import os
import re
import uuid
import threading
from flask import request, Response
from utils.WXBizJsonMsgCrypt import WXBizJsonMsgCrypt

# 导入自定义模块
from WeCom_Bot import Bot,logger
from utils.stream_utils import MakeMixedStream,MakeTextStream,EncryptMessage, stream_manager
from dotenv import load_dotenv

load_dotenv()

# 辅助函数定义
def get_json_wechat_crypt(if_bot = False):
    """获取企业微信加密工具实例"""
    token = os.getenv('Token', '')
    encoding_aes_key = os.getenv('EncodingAESKey', '')
    # 如果是机器人回调，corpid为空
    corpid = '' if if_bot else os.getenv('corpid', '')
    
    return WXBizJsonMsgCrypt(token, encoding_aes_key, corpid)


def chatBot_callback():
    """企业微信回调接口"""
    
    # 获取加密工具
    bot_wxcrypt = get_json_wechat_crypt(if_bot=True)
    
    if request.method == 'GET':
        # URL验证
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')
        logger.info(f"URL验证请求: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr}")
        ret, reply = bot_wxcrypt.VerifyURL(msg_signature, timestamp, nonce, echostr)
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
            
            if not bot_wxcrypt:
                logger.error("加密工具未初始化")
                return 'Encryption tool not initialized', 500
            
            ret, decrypted_msg = bot_wxcrypt.DecryptMsg(encrypt_msg, msg_signature, timestamp, nonce)
            if ret != 0:
                logger.error(f"消息解密失败，错误码: {ret}")
                return 'Decryption failed', 400
            
            # logger.info(f"解密后的消息: {decrypted_msg}")
            
            message_info = parse_message(decrypted_msg)
            if not message_info:
                logger.error("消息解析失败")
                return 'Parse failed', 400
            
            # logger.info(f"解析后的消息信息: {message_info}")
            from_user = message_info["from_user"]
            msgtype = message_info['msgtype']
            stream_id = message_info.get('stream_id', '')
            chatid = message_info.get('chatid', '')
            
            if msgtype == 'text' and message_info['content']:
                # 文本消息处理 - 启动思考流程
                content = message_info['content']
                # logger.info(f"收到文本消息: {content}")

                # 生成stream_id
                stream_id = str(uuid.uuid4())
                # 存储完整响应
                full_res = []
                # 创建流式任务（立即启动独立线程处理）
                stream_success = stream_manager.create_stream(
                    stream_id, content, from_user, 
                    msgid=message_info.get('msg_id', ''), 
                    chatid=chatid,
                    accumulated_content=full_res
                )
                if not stream_success:
                    error_message = "创建思考任务失败"
                    stream = MakeTextStream(stream_id, error_message, finish=True)
                    resp = EncryptMessage(bot_wxcrypt,nonce, timestamp, stream)
                    if resp:
                        return Response(response=resp, mimetype="text/plain")
                    else:
                        return 'Encryption failed', 500
                # 这是汇总消息功能
                if content.startswith("汇总消息") and stream_success:
                # 两种情况：1. 汇总消息（默认本群） 2. 汇总消息：群聊名  
                    def process_chat_summary():
                        try:
                            # 确定要汇总的群聊
                            match = re.match(r'^汇总消息[：:]\s*(.*)', content)
                            if match:
                                chatname = match.group(1).strip()
                                useid = False
                            else:
                                chatname = chatid
                                useid = True
                            response = Bot.SummarizeChat(chatname, stream_manager.add_stream_chunk, stream_id, 
                                                        full_response=full_res, useid=useid,user_id=from_user)
                            stream_manager.update_stream_message(stream_id, response)
                            stream_manager.add_stream_chunk(stream_id, "", True)
                        except Exception as e:
                            logger.error(f"大模型生成时出错: {str(e)}")
                            error_msg = "处理您的请求时出错，请稍后重试。"
                            stream_manager.add_stream_chunk(stream_id, error_msg, True)
                    threading.Thread(target=process_chat_summary, daemon=True).start()
                # 这是查询功能
                else:
                    if stream_success:
                        if content == "功能介绍":
                            welcom_str = f'''
                            我是米小度，一站式医疗智能助手：系统操作指导、法规文献查询与设备参数解析。
                            您可以通过以下方式与我互动：
                            1. 系统操作指导：询问关于系统的操作步骤、设置方法等。\n例如:"@米小度 SPD系统如何登录"
                            2. 法规文献查询：查找相关的医疗法规、政策文件等。\n例如:"@米小度 我国医疗器械管理条例介绍"
                            3. 设备参数解析：解释和解析医疗设备的参数和功能。\n例如:"@米小度 骨科识别仪的参数"
                            4. 您也可以@我，总结指定群聊最近一天的群聊消息。\n例如:"@米小度 汇总消息：群聊名"
                            '''
                            stream_manager.add_stream_chunk(stream_id, welcom_str, True)
                        else:    
                            def process_model_query():
                                try:
                                    # 调用Bot的Rag_Query进行查询
                                    response = Bot.Rag_Query(content,stream_manager.add_stream_chunk,stream_id,full_response=full_res,user_id=from_user)
                                    
                                    # 更新完整消息
                                    stream_manager.update_stream_message(stream_id, response)
                                    stream_manager.add_stream_chunk(stream_id, "", True)
                                except Exception as e:
                                    logger.error(f"大模型生成时出错: {str(e)}")
                                    error_msg = "处理您的请求时出错，请稍后重试。"
                                    stream_manager.add_stream_chunk(stream_id, error_msg, True)
                            threading.Thread(target=process_model_query, daemon=True).start()

                thinking_message = "米小度正在思考中,请稍候..."
                stream = MakeTextStream(stream_id, thinking_message, finish=False)
                resp = EncryptMessage(bot_wxcrypt,nonce, timestamp, stream)
                if resp:
                    return Response(response=resp, mimetype="text/plain")
                else:
                    return 'Encryption failed', 500

            # # To Do
            # elif msgtype == 'event':
            #     # 接收事件
            #     if message_info['event']['eventtype']:
            #         event_type = message_info['event']['eventtype']
            #     # 事件类型分类处理
            #     if event_type == 'enter_chat':
            #         # 进入会话事件，只在单聊时触发

            #         pass
                
            elif msgtype == 'stream':
                # 流式消息处理 - 逐步返回内容
                if stream_id:
                    msg_id = message_info.get('msg_id', '')
                    # logger.info(f"收到流式消息请求，stream_id: {stream_id}, msg_id: {msg_id}")
                    # 初始化wxcrypt对象用于流式消息加密
                    wxcrypt_stream = get_json_wechat_crypt(if_bot=True)
                    if not wxcrypt_stream and bot_wxcrypt:
                        # 如果获取失败，回退到原始的bot_wxcrypt对象
                        wxcrypt_stream = bot_wxcrypt
                        # logger.warning(f"使用回退bot_wxcrypt对象进行流式消息加密")
                    # logger.info(f"wxcrypt_stream对象状态: {'已初始化' if wxcrypt_stream else '未初始化'}")
                    
                    # 重复请求检测
                    duplicate_check_file = f"_cache/{stream_id}_last_msg.txt"
                    try:
                        # 检查是否是重复请求
                        if os.path.exists(duplicate_check_file):
                            with open(duplicate_check_file, 'r') as f:
                                last_msg_id = f.read().strip()
                            
                            if last_msg_id == msg_id:
                                logger.warning(f"检测到重复请求，忽略: {msg_id}")
                                return Response(response="success", mimetype="text/plain")
                        # 确保目录存在
                        os.makedirs(os.path.dirname(duplicate_check_file), exist_ok=True)
                        # 记录当前请求ID
                        with open(duplicate_check_file, 'w') as f:
                            f.write(msg_id)
                    except Exception as e:
                        logger.error(f"重复请求检测失败: {e}")
                    try:
                        # 流式推送
                        response_stream_id, content, is_finished = stream_manager.get_next_unread_message(stream_id)
                        if response_stream_id is None:
                            # 流式任务不存在，使用更低级别日志而非警告
                            logger.debug(f"流式任务不存在: {stream_id}")
                            return Response(response="success", mimetype="text/plain")
                        # 当内容存在，任务未完成时，生成流式文本消息
                        if not is_finished:
                            stream = MakeTextStream(stream_id, content, finish=is_finished)
                            # logger.info(f"生成流式消息: {stream[:100]}..." if isinstance(stream, str) else f"生成流式消息对象")
                        # 当内容存在，且任务完成时，生成图文混合消息
                        if is_finished:
                            full_content = stream_manager.get_full_content(stream_id)
                            stream = MakeMixedStream(stream_id, full_content, finish=is_finished)
                        if wxcrypt_stream:
                            ret, resp = wxcrypt_stream.EncryptMsg(stream, nonce, timestamp)
                            if ret != 0:
                                logger.error(f"加密失败，错误码: {ret}")
                                # 加密失败时，直接返回原始流作为文本响应
                                return Response(response=stream, mimetype="application/json")
                            # logger.info(f"加密成功，返回企业微信标准格式响应")
                            # EncryptMsg返回的已经是一个完整的JSON字符串，直接返回
                            return Response(response=resp, mimetype="application/json")
                    except Exception as e:
                        logger.error(f"处理流式消息失败: {e}")
                        logger.error(f"异常堆栈: {traceback.format_exc()}")
                        return Response(response="success", mimetype="text/plain")

                    finally:
                        # 检查最终内容中是否含有图片url,图片url示例:https://manage.midoclouds.com/files/fbccf553-a85e-4adc-810c-51a91113103e/file-preview?timestamp=1762139115&nonce=9629&sign=lTOouA
                        # 调用MakeMixedStream函数,推送最终的图文混合消息
                        if is_finished and 'response_stream_id' in locals() and response_stream_id:
                            try:
                                if os.path.exists(duplicate_check_file):
                                    os.remove(duplicate_check_file)
                                # logger.info(f"流式任务完成，清理重复检测文件: {stream_id}")
                                
                                # 延迟清理缓存，给企微一些时间重新请求
                                def delayed_cleanup():
                                    time.sleep(2)  # 等待2秒后清理
                                    stream_manager.cleanup_stream(stream_id)
                                cleanup_thread = threading.Thread(target=delayed_cleanup)
                                cleanup_thread.daemon = True
                                cleanup_thread.start()
                                # logger.info(f"启动延迟清理线程: {stream_id}")
                            except Exception as e:
                                logger.error(f"清理资源时发生错误: {e}")
                # 如果没有stream_id，返回成功以避免重复请求
                return Response(response="success", mimetype="text/plain")

            return 'Message type not supported', 200
        except Exception as e:
            logger.error(f"处理消息异常: {str(e)}")
            return 'Internal server error', 500

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
            'chattype': json_data.get('chattype', ''),
        }
        
        # 根据消息类型提取内容
        if message_info['msgtype'] == 'text':
            # 提取的内容去掉@机器人的部分，类似@test机器人 如何登录spd系统
            message_info['content'] = re.sub(r'@\w+\s*', '', json_data.get('text', {}).get('content', ''))
            # logger.info(f"提取的文本内容: {message_info['content']}")
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

        