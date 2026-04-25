import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from wd.qtr.gsi_builder.logger import Logger

logger = Logger.get_logger(__name__)

DEFAULT_RECIPIENTS = "naveen.kumar.pentakota@ADP.com,Krati.Garg@ADP.com,Vamsikrishna.Pulugundla@ADP.com,manideep.bijjam@ADP.com,aaqil.ghori@adp.com"


class EmailNotifier:
    def __init__(self, smtp_host="smtprelay.gslb.es.oneadp.com", smtp_port=25, recipient=None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.recipient = recipient or os.getenv("GSI_EMAIL_RECIPIENTS", DEFAULT_RECIPIENTS)

    def send_notification(self, start_time, params, status, error_msg=None, env=None, job_url=None):
        """Send email notification with job details."""
        try:
            runtime = (datetime.now(start_time.tzinfo) - start_time).total_seconds()
            subject = f"WD QTR GSI Builder - {status}"
            body = f"""
Job Status: {status}
Environment: {env or "N/A"}
Execution Date/Time: {start_time.strftime("%Y-%m-%d %H:%M:%S %Z")}
Runtime: {runtime:.2f} seconds
Site ID: {params.get("site_id", "N/A")}
Year: {params.get("year", "N/A")}
Quarter: {params.get("quarter", "N/A")}
"""
            if job_url:
                body += f"\nJob Link: {job_url}"
            if error_msg:
                body += f"\nError: {error_msg}"

            from_email = "ADP_Communication@adp.com" if env and env.lower() == "prod" else "ADP_Communication-QA2@adp.com"

            msg = MIMEMultipart()
            msg["From"] = from_email
            msg["To"] = self.recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.send_message(msg)

            logger.info(f"Email sent to {self.recipient}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
