CREATE TABLE wecom_messages(
    msgid varchar(255) NOT NULL PRIMARY KEY,
    action varchar(50) NOT NULL,
    "from" varchar(255) NOT NULL,
    tolist text[] NOT NULL,
    roomid varchar(255),
    chat_name varchar(255),
    msgtime bigint NOT NULL,
    msgtype varchar(50) NOT NULL,
    content jsonb NOT NULL
);
CREATE INDEX idx_wecom_messages_action ON public.wecom_messages USING btree (action);
CREATE INDEX idx_wecom_messages_from ON public.wecom_messages USING btree ("from");
CREATE INDEX idx_wecom_messages_roomid ON public.wecom_messages USING btree (roomid);
CREATE INDEX idx_wecom_messages_chat_name ON public.wecom_messages USING btree (chat_name);
CREATE INDEX idx_wecom_messages_msgtime ON public.wecom_messages USING btree (msgtime);
CREATE INDEX idx_wecom_messages_msgtype ON public.wecom_messages USING btree (msgtype);
COMMENT ON TABLE wecom_messages IS '企业微信消息表，存储企业微信用户会话消息记录';
COMMENT ON COLUMN wecom_messages.msgid IS '消息id，消息的唯一标识，企业可以使用此字段进行消息去重';
COMMENT ON COLUMN wecom_messages.action IS '消息动作，目前有send(发送消息)/recall(撤回消息)/switch(切换企业日志)三种类型';
COMMENT ON COLUMN wecom_messages."from" IS '消息发送方id。同一企业内容为userid，非相同企业为external_userid。消息如果是机器人发出，也为external_userid';
COMMENT ON COLUMN wecom_messages.tolist IS '消息接收方列表，可能是多个，同一个企业内容为userid，非相同企业为external_userid';
COMMENT ON COLUMN wecom_messages.roomid IS '群聊消息的群id。如果是单聊则为空';
COMMENT ON COLUMN wecom_messages.chat_name IS '群聊名称，单聊则为用户名';
COMMENT ON COLUMN wecom_messages.msgtime IS '消息发送时间戳，utc时间，ms单位';
COMMENT ON COLUMN wecom_messages.msgtype IS '消息类型';
COMMENT ON COLUMN wecom_messages.content IS '消息内容，json格式';