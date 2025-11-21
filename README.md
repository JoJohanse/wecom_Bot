# 企业微信机器人部署文档

## 项目简介

本项目是一个企业微信机器人服务，主要功能包括：
- 接收企业微信消息并自动回复
- 集成大语言模型（LLM）提供智能对话能力
- 支持RAG（检索增强生成）知识库查询
- 聊天记录保存和定时清理
- 基于Flask的服务接口

## 系统架构

- **前端**：企业微信客户端
- **后端**：Flask 服务
- **数据库**：PostgreSQL
- **AI服务**：Dify知识库，大模型服务商API

## 环境要求

- Python 3.13+
- PostgreSQL数据库
- 企业微信开发者账号
- 大模型API访问权限
- 知识库服务访问权限

## 安装步骤
### 1. 创建虚拟环境

#### 使用conda（推荐）

```bash
conda env create -f environment.yaml
conda activate wecom_bot
```

#### 或使用pip

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 3. 配置环境变量

复制并编辑`.env`文件，填写必要的配置信息：

```bash
cp .env.example .env 
```

编辑`.env`文件，配置以下内容：

```
### 企微配置 ###
export Token=''# 智能机器人token
export EncodingAESKey=''# 智能机器人加密key
export corpid='' # 企业id
export secret='' # 生成密钥
export prikey_path = './src/utils/WeComFinanceSdk_python/prikey.pem' # 密钥放这个路径
### 企微配置 ###

### 大模型配置 ###
export llm_url='https://api.deepseek.com/v1' # 支持openai接口的都可以
export llm_name='deepseek-reasoner'
export llm_key='sk-****************'
### 大模型配置 ###

### dify知识库与数据库配置 ###
export dify_url='https://xxx.xxx.com/v1' # 你的dify域名
export db_url='postgresql+psycopg2://****************' # 你的数据库链接，项目使用postsql，你可以自己修改
export dify_key='app-************* # dify聊天流调用key
### dify知识库与数据库配置 ###

### 端口配置 ###
export port=3456
### 端口配置 ###
```

### 4. 设置日志目录

确保日志目录存在并有写入权限：

```bash
mkdir -p log
```

### 5. 数据库属性
表名：wecom_messages

字段名 | 类型 | 描述
--- | --- | ---
msgid | VARCHAR(255) | 消息id，消息的唯一标识，企业可以使用此字段进行消息去重
action | VARCHAR(50) | 消息动作，目前有send(发送消息)/recall(撤回消息)/switch(切换企业日志)三种类型
from | VARCHAR(255) | 消息发送方id。同一企业内容为userid，非相同企业为external_userid。消息如果是机器人发出，也为external_userid
tolist | VARCHAR(255) | 消息接收方列表，可能是多个，同一个企业内容为userid，非相同企业为external_userid
roomid | VARCHAR(255) | 群聊消息的群id。如果是单聊则为空
chat_name | VARCHAR(255) | 群聊名称，单聊则为用户名
msgtime | BIGINT | 消息发送时间戳，utc时间，ms单位
msgtype | VARCHAR(50) | 消息类型
content | JSON | 消息内容，json格式

## 企业微信配置

1. 在企业微信管理后台创建应用
2. 配置服务器回调URL：`https://your-domain.com/wechat/callback`
3. 设置Token和EncodingAESKey（与`.env`文件中的配置一致）
4. 启用接收消息权限

## 运行服务

```bash
cd src
python run.py
```

## 功能说明

### 1. 聊天功能

机器人可以接收企业微信消息，并调用大模型生成回复。支持的消息类型包括文本、图片等。

### 2. RAG知识库查询

通过`Rag_Query`方法，机器人可以查询配置的知识库，为用户提供基于知识库的精准回答。

### 3. 数据持久化

所有聊天记录都会保存到PostgreSQL数据库中，便于后续分析和查询。

### 4. 定时任务

系统内置了定时清理功能，默认每天凌晨3点自动清理7天前的聊天记录，避免数据库过大。

## 监控与日志

### 日志文件

- 应用日志：`/home/sjr/wecom_Bot/log/WeComBot.log` # logger = logging.getLogger('WeComBot')
- 服务日志：`/home/sjr/wecom_Bot/log/server.log` # nohup python run.py > wecom_Bot/log/server.log 2>&1 &

### 查看日志

```bash
tail -f wecom_Bot/log/WeComBot.log
```
### 环境变量更新


修改`.env`文件后，需要重启服务：
