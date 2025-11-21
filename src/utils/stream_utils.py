#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式消息处理工具 - 基于stream_manager.py重构版本
负责管理流式响应与企业微信stream_id的对应关系
支持队列式的消息处理机制
"""
import json
import base64
import hashlib
import re
import requests
import threading
import logging
from queue import Queue
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger('WeComBot')
# 流式消息管理类
class StreamManager:
    """
    流式响应管理器
    负责管理流式消息队列、状态跟踪和内容累积
    """
    
    def __init__(self):
        # 存储活跃的处理线程
        self.active_threads = {}
        # 存储流式消息的字典
        self.streams = {}
        # 存储用户消息队列的字典
        self.message_queues = defaultdict(Queue)
        # 线程锁，保护共享资源
        self.lock = threading.Lock()
        # 任务状态
        self.task_status = {}
    
    def create_stream(self, stream_id, content, from_user, msgid=None, chatid=None,accumulated_content=[]):
        """
        创建新的流式任务
        
        Args:
            stream_id (str): 流ID
            content (str): 用户输入内容
            from_user (str): 发送者
            msgid (str, optional): 消息ID
            chatid (str, optional): 会话ID
            
        Returns:
            bool: 创建是否成功
        """
        try:
            # 初始化流信息
            with self.lock:
                # 创建流数据
                self.streams[stream_id] = {
                    "content": content,
                    "from_user": from_user,
                    "status": "processing",  # pending, processing, completed, error
                    "created_at": datetime.now().isoformat(),
                    "accumulated_content": accumulated_content if accumulated_content else [],  # 累积的内容
                    "is_finished": False,
                    "msgid": msgid,
                    "chatid": chatid,
                    "error_message": ""
                }
                
                # 初始化消息队列
                self.message_queues[stream_id] = Queue()
                
                # 设置任务状态
                self.task_status[stream_id] = 'running'
                
                logger.info(f"创建流式任务: stream_id={stream_id}, content_length={len(content)}")
            
            # 创建并启动处理线程
            thread = threading.Thread(
                target=self._process_stream,
                args=(stream_id, content, from_user, msgid, chatid),
                daemon=True
            )
            thread.start()
            
            with self.lock:
                self.active_threads[stream_id] = thread
            
            return True
            
        except Exception as e:
            logger.error(f"创建流式任务失败: {str(e)}")
            return False
    
    def _process_stream(self, stream_id, content, from_user, msgid=None, chatid=None):
        """
        处理流式任务的线程函数
        负责初始化流信息和管理状态
        """
        try:
            # 更新流信息
            with self.lock:
                if stream_id in self.streams:
                    self.streams[stream_id]['msgid'] = msgid
                    self.streams[stream_id]['chatid'] = chatid
        
        except Exception as e:
            error_message = f"处理流式任务失败: {str(e)}"
            logger.error(f"流式任务处理异常: {error_message}")
            
            with self.lock:
                if stream_id in self.streams:
                    self.streams[stream_id]['status'] = 'error'
                    self.streams[stream_id]['error_message'] = str(e)
                    self.streams[stream_id]['is_finished'] = True
                    self.task_status[stream_id] = 'failed'
                    self.message_queues[stream_id].put((error_message, True))
        
        finally:
            # 清理线程引用（线程结束时）
            with self.lock:
                if stream_id in self.active_threads:
                    del self.active_threads[stream_id]
    
    def add_stream_chunk(self, stream_id, chunk_content, is_finished=False):
        """
        向指定流添加一个数据块
        这个方法供外部调用，用于将大模型生成的每个chunk添加到流中
        
        Args:
            stream_id (str): 流ID
            chunk_content (str): 数据块内容
            is_finished (bool): 是否是最后一个数据块
            
        Returns:
            bool: 添加是否成功
        """
        try:
            with self.lock:
                if stream_id in self.streams:
                    # 累积内容
                    self.streams[stream_id]['accumulated_content'].append(chunk_content)
                    accumulated = ''.join(self.streams[stream_id]['accumulated_content'])
                    
                    # 企业微信每次获取的都是完整的累积内容，避免覆盖问题
                    while not self.message_queues[stream_id].empty():
                        try:
                            self.message_queues[stream_id].get_nowait()
                        except Exception:
                            pass
                    
                    # 将累积的完整内容放入队列
                    self.message_queues[stream_id].put((accumulated, is_finished))
                    
                    # logger.info(f"添加流数据块: stream_id={stream_id}, chunk长度={len(chunk_content)}")
                    # logger.info(f"添加文本块: {chunk_content[:5]}... 累积内容长度: {len(accumulated)}, 是否完成={is_finished}")
                  
                    # 如果是最后一个数据块，更新状态
                    if is_finished:
                        self.streams[stream_id]['status'] = 'completed'
                        self.streams[stream_id]['is_finished'] = True
                        self.task_status[stream_id] = 'completed'
                        # logger.info(f"流式任务完成: stream_id={stream_id}")
                    
                    return True
            return False
        except Exception as e:
            logger.error(f"添加流数据块失败: {str(e)}")
            return False
    
    def update_stream_message(self, stream_id, full_message):
        """
        更新流的完整消息内容
        
        Args:
            stream_id (str): 流ID
            full_message (str): 完整的消息内容
            
        Returns:
            bool: 更新是否成功
        """
        
        try:
            with self.lock:
                if stream_id in self.streams:
 
                    # 更新累积内容
                    self.streams[stream_id]['accumulated_content'] = [full_message]                   
                    # 更新任务状态
                    self.streams[stream_id]['status'] = 'completed'
                    self.streams[stream_id]['is_finished'] = True
                    self.task_status[stream_id] = 'completed'
                    
                    # 将完整内容放入队列
                    self.message_queues[stream_id].put((full_message, True))
                    
                    # logger.info(f"更新完整消息:{full_message},消息长度={len(full_message)}")
                    return True
            return False
        except Exception as e:
            logger.error(f"更新流完整消息失败: {str(e)}")
            return False
    
    def handle_error(self, stream_id, error_message):
        """
        处理流式任务错误
        
        Args:
            stream_id (str): 流ID
            error_message (str): 错误消息
            
        Returns:
            bool: 处理是否成功
        """
        
        try:
            with self.lock:
                if stream_id in self.streams:
                    # 更新状态
                    self.streams[stream_id]['status'] = 'error'
                    self.streams[stream_id]['error_message'] = error_message
                    self.streams[stream_id]['is_finished'] = True
                    self.task_status[stream_id] = 'failed'
                    
                    # 添加错误消息到队列
                    self.message_queues[stream_id].put((error_message, True))
                    
                    logger.info(f"处理流式任务错误: stream_id={stream_id}, {error_message}")
                    return True
            return False
        except Exception as e:
            logger.error(f"处理流式任务错误失败: {str(e)}")
            return False
    
    def get_full_content(self, stream_id):
        with self.lock:
            if stream_id in self.streams:
                return ''.join(self.streams[stream_id]['accumulated_content'])
        return ""

    def get_next_unread_message(self, stream_id):
        """
        获取下一条未读消息
        参考stream_manager.py的实现，改进了消息处理逻辑
        
        Args:
            stream_id (str): 流ID
            
        Returns:
            tuple: (stream_id, content, is_finished)
        """
        try:
            
            # 检查流是否存在
            if stream_id not in self.streams:
                logger.warning(f"流式任务不存在: {stream_id}")
                return None, "", True
            
            # 获取当前流信息
            with self.lock:
                stream_data = self.streams[stream_id]
                status = stream_data.get('status', 'processing')
                is_finished = stream_data.get('is_finished', False)
                
                # 预先获取累积内容，避免在多处重复获取
                accumulated_content_list = stream_data.get('accumulated_content', [])
                accumulated_content = ''.join(accumulated_content_list)
            
            # 尝试从队列获取消息
            try:
                content, is_finished = self.message_queues[stream_id].get(block=False)
                return stream_id, content, is_finished
            except Exception:
                # 队列为空，检查任务状态
                with self.lock:
                    # 无论任务状态如何，只要有累积内容就返回
                    if accumulated_content:
                        # logger.info(f"返回累积内容: stream_id={stream_id}, 长度={len(accumulated_content)}, 任务状态={status}")
                        return stream_id, accumulated_content, is_finished
                    elif status in ['completed', 'failed'] or is_finished:
                        logger.info(f"任务已完成/失败: {status}, 但无累积内容")
                        # 如果是错误状态，优先使用错误消息
                        if status == 'failed':
                            fallback_content = stream_data.get('error_message', "处理完成")
                        else:
                            fallback_content = "处理完成"
                        return stream_id, fallback_content, True
                    else:
                        return stream_id, "", False
            
        except Exception as e:
            logger.error(f"获取未读消息失败: {str(e)}")
            import traceback
            logger.error(f"异常堆栈: {traceback.format_exc()}")
            return None, "处理消息时发生错误，请稍后重试。", True
    
    def cleanup_stream(self, stream_id):
        """
        清理流式任务资源
        参考stream_manager.py的资源清理逻辑
        
        Args:
            stream_id (str): 流ID
        """
        try:
            with self.lock:
                # 清理流信息
                if stream_id in self.streams:
                    del self.streams[stream_id]
                    # logger.info(f"清理流信息: {stream_id}")
                
                    
        except Exception as e:
            logger.error(f"清理流式任务资源失败: {str(e)}")
    
    def get_stream_status(self, stream_id):
        """
        获取流式任务状态
        参考stream_manager.py的状态查询功能
        
        Args:
            stream_id (str): 流ID
            
        Returns:
            str: 任务状态
        """
        try:
            with self.lock:
                if stream_id in self.streams:
                    return self.streams[stream_id].get('status', 'unknown')
                return 'not_found'
        except Exception as e:
            logger.error(f"获取流式任务状态失败: {str(e)}")
            return 'error'

# 创建全局的流管理器实例
stream_manager = StreamManager()

def MakeTextStream(stream_id, content, finish):
    """
    构建流式文本消息
    
    Args:
        stream_id (str): 流ID
        content (str): 消息内容
        finish (bool): 是否是最终消息
        
    Returns:
        str: JSON格式的流式消息
    """
    try:
        # 确保content不为空
        if not content:
            if finish:
                content = "我是米小度，很高兴为您服务！"
            else:
                content = "米小度正在思考中,请稍后..."

        plain = {
            "msgtype": "stream",
            "stream": {
                "id": stream_id,
                "finish": finish,
                "content": content
            }
        }
        
        # 使用ensure_ascii=False确保中文正确编码
        result = json.dumps(plain, ensure_ascii=False)
        logger.debug(f"文本流式消息构建成功: {result[:100]}...")
        return result
    except Exception as e:
        # 导入日志模块
        logger.error(f"构建文本流式消息失败: {str(e)}", exc_info=True)
        # 返回默认错误消息
        error_plain = {
            "msgtype": "stream",
            "stream": {
                "id": stream_id,
                "finish": True,
                "content": "抱歉，处理消息时发生错误，请稍后重试。"
            }
        }
        return json.dumps(error_plain, ensure_ascii=False)

def get_img(img_url):
    """
    从URL获取图片内容
    
    Args:
        img_url (str): 图片URL
        
    Returns:
        bytes: 图片内容的base64编码
        str: 图片内容的md5值
    """
    try:
        ori_img = requests.get(img_url).content

        b64 = base64.b64encode(ori_img).decode('utf-8')
        md5 = hashlib.md5(ori_img).hexdigest()
        # 清除图片缓存
        del ori_img
        return b64,md5
    except Exception as e:
        logger.error(f"获取图片内容失败: {str(e)}")
        return None, None
        
# To do
def MakeMixedStream(stream_id,full_content,finish):
    """
    图文混合流式消息
    在包含图片的情况下，使用图文混排格式
    若不包含图片，使用普通文本流式消息
    
    Args:
        stream_id (str): 流ID
        content (str): 消息内容
        finish (bool): 是否是最终消息
        
    Returns:
        str: JSON格式的图文混合流式消息
    """
    try:
        # 纯文本
        text_content = full_content
        
        # 首先提取markdown格式的图片URL链接"![image](/files/)",示例 ![image](/files/0a29d152-de00-41a7-82bd-1b924877b42b/file-preview?timestamp=1762022993&nonce=4f55&sign=uGTp-w)
        # 然后拼接为完整的图片URL,示例 https://manage.midoclouds.com/files/0a29d152-de00-41a7-82bd-1b924877b42b/file-preview?timestamp=1762022993&nonce=4f55&sign=uGTp-w
        img_prefix = "https://manage.midoclouds.com/files/"
        image_pattern = r'!\[image\]\(/files/([^)]+)\)'
        matches = re.finditer(image_pattern, full_content)
        if matches:
            msg_item = []
            for match in matches:
                # 通过url获取图片base64,md5编码
                img_url = img_prefix + match.group(1)
                # logger.info(f"获取图片URL: {img_url}")
                img_b64,img_md5= get_img(img_url)
                if img_b64 and img_md5:
                    msg_item.append({
                        "msgtype": "image",
                        "image": {
                            "base64": img_b64,
                            "md5": img_md5
                        }
                    })
                # 从content中移除完整的图片URL
                text_content = text_content.replace(match.group(0), "")

            plain = {
                "msgtype": "stream",
                "stream": {
                    "id": stream_id,
                    "finish": finish,
                    "content": text_content,
                    "msg_item": msg_item
                }
            }
        else:
            plain = {
            "msgtype": "stream",
            "stream": {
                "id": stream_id,
                "finish": finish,
                "content": text_content
            }
        }
    except Exception as e:
            logger.error(f"构建图文混合流式消息失败: {str(e)}", exc_info=True)
            # 返回默认错误消息
            error_plain = {
                "msgtype": "stream",
                "stream": {
                    "id": stream_id,
                    "finish": True,
                    "content": "抱歉，处理消息时发生错误，请稍后重试。"
                }
            }
            return json.dumps(error_plain, ensure_ascii=False)
        
    return json.dumps(plain, ensure_ascii=False)

def EncryptMessage(wxcrypt, nonce, timestamp, stream):
    """
    确保消息正确加密并返回给企业微信
    
    Args:
        wxcrypt: 加密对象
        reply_msg: 回复消息
        nonce: 随机字符串
        timestamp: 时间戳
        stream: 流式消息
        
    Returns:
        bytes/str: 加密后的消息
    """
    try:
        # 检查wxcrypt对象
        if not wxcrypt:
            logger.error("加密失败: wxcrypt对象未初始化")
            # 如果没有wxcrypt对象，仍然返回stream以便调试
            return stream
        
        # 确保stream是字符串
        if not isinstance(stream, str):
            logger.warning(f"stream不是字符串类型，进行转换: {type(stream)}")
            stream = str(stream)
        
        # logger.info(f"准备加密消息: 消息长度={len(stream)}")
        
        # 调用企业微信提供的加密方法
        # 注意：根据WXBizJsonMsgCrypt.py的实现，参数顺序可能需要调整
        ret, resp = wxcrypt.EncryptMsg(stream, nonce, timestamp)
        
        if ret != 0:
            logger.error(f"加密失败，错误码: {ret}")
            # 为了调试，在加密失败时仍然返回stream
            return stream
        
        # 确保返回的是字节类型
        if isinstance(resp, str):
            resp = resp.encode('utf-8')
        
        logger.info(f"加密成功: 响应长度={len(resp)}")
        return resp
    except Exception as e:
        logger.error(f"加密过程异常: {str(e)}")
        # 发生异常时，返回原始流以确保功能不中断
        return stream