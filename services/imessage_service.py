"""邮件提醒服务"""
import logging
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import HOST, PORT

logger = logging.getLogger(__name__)

_APP_URL = f"http://{HOST}:{PORT}/"


class IMessageService:
    def _needs_auth(self, config: dict) -> bool:
        """判断是否需要 SMTP 认证（有用户名和密码才认证）"""
        return bool(config.get("smtp_user")) and bool(config.get("smtp_pass"))

    def _smtp_kwargs(self, config: dict) -> dict:
        """根据端口号自动选择 TLS 模式：465=直接SSL，587=STARTTLS，其他=不加密"""
        host = config.get("smtp_host", "")
        port = int(config.get("smtp_port", 587))
        kwargs = dict(hostname=host, port=port)

        if port == 465:
            # 直接 SSL 连接
            kwargs["use_tls"] = True
        elif port == 587:
            # 明文连接后 STARTTLS 升级
            kwargs["use_tls"] = False
            kwargs["start_tls"] = True
        else:
            # 其他端口不加密
            kwargs["use_tls"] = False
            kwargs["start_tls"] = False

        return kwargs

    async def send_reminder(self, config: dict, subject: str, body_html: str) -> bool:
        if not config.get("enabled"):
            return False

        try:
            sender = config.get("smtp_user") or "educhat@localhost"
            recipient = config["to_email"]

            msg = MIMEMultipart()
            msg["From"] = f"EduChat <{sender}>"
            msg["To"] = recipient
            msg["Subject"] = subject

            html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#FFFEF7;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#FFFEF7;padding:20px 0;">
<tr><td align="center">
<table width="580" cellpadding="0" cellspacing="0" style="background:#FBF6EC;border-radius:16px;border:1px solid rgba(180,146,58,0.25);overflow:hidden;">

  <!-- 金色顶部装饰条 -->
  <tr><td style="height:4px;background:linear-gradient(90deg,#B8923A,#D4A853,#E8C777,#D4A853,#B8923A);"></td></tr>

  <!-- Logo 区 -->
  <tr><td style="padding:28px 32px 12px;text-align:center;">
    <span style="font-size:11px;color:#D4A853;letter-spacing:3px;">✦ ─────── ✦ ─────── ✦</span>
    <h1 style="margin:12px 0 4px;font-size:22px;font-weight:700;color:#3C3224;">
      <span style="color:#9A7A2E;">◆</span> EduChat 冒险提醒
    </h1>
    <p style="margin:0;font-size:12px;color:#A69B88;letter-spacing:1px;">ADVENTURE NOTIFICATION</p>
  </td></tr>

  <!-- 分割线 -->
  <tr><td style="padding:0 32px;">
    <div style="height:1px;background:linear-gradient(90deg,transparent,rgba(180,146,58,0.3),transparent);"></div>
  </td></tr>

  <!-- 正文内容 -->
  <tr><td style="padding:20px 32px;">
    {body_html}
  </td></tr>

  <!-- 激励语 -->
  <tr><td style="padding:0 32px 20px;">
    <div style="background:rgba(255,253,245,0.8);border:1px solid rgba(180,146,58,0.15);border-radius:10px;padding:16px 20px;text-align:center;">
      <p style="margin:0 0 6px;font-size:13px;color:#9A7A2E;font-weight:600;">✨ 冒险者，前方还有未探索的领域等待着你！</p>
      <p style="margin:0;font-size:12px;color:#7A6E5D;">每一次复习都是经验值的积累，坚持就能突破下一个冒险等阶。</p>
    </div>
  </td></tr>

  <!-- CTA 区域 -->
  <tr><td style="padding:0 32px 24px;text-align:center;">
    <div style="display:inline-block;padding:10px 32px;background:linear-gradient(135deg,#B8923A,#D4A853,#E8C777);color:#fff;font-size:14px;font-weight:600;border-radius:24px;letter-spacing:1px;">
      ◆ 立即开始冒险
    </div>
    <p style="margin:8px 0 0;font-size:12px;color:#7A6E5D;">
      请在浏览器中打开：<span style="color:#9A7A2E;font-weight:600;text-decoration:underline;">{_APP_URL}</span>
    </p>
  </td></tr>

  <!-- 底部分割线 -->
  <tr><td style="padding:0 32px;">
    <div style="height:1px;background:linear-gradient(90deg,transparent,rgba(180,146,58,0.3),transparent);"></div>
  </td></tr>

  <!-- 页脚 -->
  <tr><td style="padding:16px 32px 20px;text-align:center;">
    <p style="margin:0;font-size:11px;color:#A69B88;">
      ◇ EduChat 智能学习助手 · 让每一次学习都成为冒险 ◇
    </p>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            send_kwargs = self._smtp_kwargs(config)
            if self._needs_auth(config):
                send_kwargs["username"] = config["smtp_user"]
                send_kwargs["password"] = config["smtp_pass"]

            await aiosmtplib.send(msg, **send_kwargs)
            logger.info(f"Reminder email sent to {recipient}")
            return True
        except Exception as e:
            logger.error(f"Failed to send reminder email: {e}")
            return False

    async def test_connection(self, config: dict) -> dict:
        try:
            kwargs = self._smtp_kwargs(config)
            smtp = aiosmtplib.SMTP(**kwargs)
            await smtp.connect()
            if self._needs_auth(config):
                await smtp.login(config["smtp_user"], config["smtp_pass"])
            await smtp.quit()
            return {"success": True, "message": "SMTP 连接测试成功"}
        except Exception as e:
            return {"success": False, "message": f"SMTP 连接失败: {str(e)}"}


imessage_service = IMessageService()
