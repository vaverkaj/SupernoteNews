from reportlab.platypus.doctemplate import NextPageTemplate
import feedparser
import json
import os
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from datetime import datetime, UTC
import time
import random
from urllib.error import HTTPError
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    BaseDocTemplate,
    Paragraph,
    Spacer,
    FrameBreak,
    Frame,
    PageTemplate,
    KeepInFrame,
    Table,
    TableStyle
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from reportlab.platypus import Image
from PIL import Image as PILImage

from io import BytesIO
import requests

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from datetime import datetime, timedelta, timezone

import uuid

import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from google.oauth2 import service_account
from googleapiclient.discovery import build

from playwright.sync_api import sync_playwright

EXT_PATH = "./bypass-paywalls-chrome-clean-master"
PROFILE = "./chrome-profile"

SCOPES = ['https://www.googleapis.com/auth/drive.file']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.pickle'
SERVICE_ACCOUNT_FILE = "service_account.json"


pdfmetrics.registerFont(TTFont("Header", "fonts/Cinzel/Cinzel-VariableFont_wght.ttf"))
pdfmetrics.registerFont(TTFont("Title", "fonts/Antonio/static/Antonio-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Paragraph", "fonts/Crimson_Text/CrimsonText-Regular.ttf"))


RSS_FEEDS = [
    "https://www.ft.com/rss/home",
]

FOLDER_ID = '1zz_ErTCZ3Jr8o3_kzdzopwsdQUjhoi7K'
SEEN_FILE = "seen_articles.json"
OUTPUT_DIR = "articles"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

def send_newspaper_email(pdf_path, recipient_email):
    # --- Configuration ---
    sender_email = "supernoteletter@gmail.com"
    sender_password = "jkzt esuf jbra ajkr" # Not your login password (see below)
    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    # --- Create the Email Container ---
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = "Your Morning Newspaper"

    # Add the body text
    body = "Please find your generated newspaper attached as a PDF."
    msg.attach(MIMEText(body, 'plain'))

    # --- Attach the PDF ---
    with open(pdf_path, "rb") as f:
        # Create the attachment object
        attachment = MIMEApplication(f.read(), _subtype="pdf")
        # Set the filename that will appear in the email
        attachment.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf_path))
        msg.attach(attachment)

    # --- Send the Email ---
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls() # Secure the connection
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(f"Success: Email sent to {recipient_email}")
        return True
    except Exception as e:
        print(f"Error: Could not send email. {e}")
        return False

def get_perfect_headline_style(title, max_width):
    best_size = 96
    best_h = 0
    
    # We test font sizes from 96 down to 40
    for size in range(96, 36, -4):
        style = ParagraphStyle(
            "Temp",
            fontName="Title", # Replace with 'Antonio-Bold'
            fontSize=size,
            leading=size * 0.92, # Very tight leading for impact
            alignment=TA_CENTER,
            # This helps prevent single-word orphans
            hyphenationLang='en_GB', 
            spaceBefore=0,
            spaceAfter=0,
            allowWidows=0
        )
        p = Paragraph(title.upper(), style)
        w, h = p.wrap(max_width, 1000)
        
        # Calculate how many lines this size results in
        line_count = h / style.leading
        
        buffer = size * 0.20
        # Logic: 
        # 1. If it fits in 1 or 2 lines at a huge size (>70), stop and use it.
        if line_count <= 2.1 and size > 70:
            return style, h + buffer
            
        # 2. If it takes 3 lines but keeps the size large (>50), this is our "Sweet Spot"
        if line_count <= 3.1 and size > 50:
            return style, h + buffer
        
        if line_count <= 4.1:
            # We continue the loop to see if we can get even larger, 
            # but we'll likely settle here.
            best_size = size
            best_h = h + buffer
            continue 

    # Fallback to the best discovered size
    final_style = ParagraphStyle("Headline", fontName="Title", fontSize=best_size, leading=best_size*0.92, spaceBefore=0, spaceAfter=0, alignment=TA_CENTER)
    return final_style, best_h

def generate_newspaper_pdf(filename: str, title: str, paragraphs: list[str], published: str):
    # Setup Page dimensions
    page_width, page_height = A4
    margin = 5 * mm
    gutter = 8 * mm
    usable_width = page_width - (2 * margin)
    usable_height = page_height - (2 * margin)
    column_width = (usable_width - gutter) / 2

    doc = BaseDocTemplate(filename, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin)

    # --- Custom Styles ---
    masthead_style = ParagraphStyle("Masthead", fontSize=48, leading=48 * 0.92, alignment=TA_CENTER, spaceBefore=0, fontName="Header")
    # headline_style = ParagraphStyle("Headline", fontSize=96, leading=96, alignment=TA_CENTER, fontName="Title")
    body_style = ParagraphStyle("Body", fontSize=24, leading=28, alignment=TA_JUSTIFY, spaceAfter=8, fontName="Paragraph")

    # --- Frame Definitions ---
    # Heights for the header section
    masthead_h = 20 * mm
    dateline_h = 5 * mm
    
    headline_style, headline_h = get_perfect_headline_style(title, usable_width)
    
    header_total_h = masthead_h + headline_h + dateline_h

    # 1. Masthead (Top)
    masthead_frame = Frame(margin, page_height - margin - masthead_h, usable_width, masthead_h, id='masthead', showBoundary=0, leftPadding=0, 
    rightPadding=0, 
    topPadding=0, 
    bottomPadding=0)
    
    dateline_frame = Frame(
        margin, 
        page_height - margin - masthead_h - dateline_h, 
        usable_width, 
        dateline_h, 
        id='dateline', 
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, showBoundary=0
    )
    
    # 2. Headline (Below Masthead)
    headline_frame = Frame(margin, page_height - margin - header_total_h, usable_width, headline_h, id='headline',leftPadding=0, 
    rightPadding=0, 
    topPadding=0, 
    bottomPadding=0, showBoundary=0)
    
    # 3. First Page Columns (Remaining space)
    col_height_first = usable_height - header_total_h
    first_left = Frame(margin, margin, column_width, col_height_first, id='f_left')
    first_right = Frame(margin + column_width + gutter, margin, column_width, col_height_first, id='f_right')

    # 4. Standard Page Columns (Full height)
    std_left = Frame(margin, margin, column_width, usable_height, id='left')
    std_right = Frame(margin + column_width + gutter, margin, column_width, usable_height, id='right')

    # --- Page Templates ---
    # Template for page 1
    first_page = PageTemplate(id='FirstPage', frames=[masthead_frame, dateline_frame,headline_frame, first_left, first_right])
    
    # Template for page 2 onwards
    following_pages = PageTemplate(id='FollowingPages', frames=[std_left, std_right])

    doc.addPageTemplates([first_page, following_pages])

    # Style for the date text
    date_style = ParagraphStyle("DateStyle", fontSize=10, fontName="Paragraph", alignment=TA_CENTER)

    dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
    eu_dt = dt.astimezone(ZoneInfo("CET"))
    # Create a Table for the dateline
    dateline_table = Table(
        [[Paragraph(eu_dt.strftime("%d %B %Y - %H:%M"), date_style)]],
        colWidths=[usable_width],
        rowHeights=[dateline_h]
    )

    dateline_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # TOP LINE
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
        # BOTTOM LINE (Creates the double line effect)
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black),
        # Padding to control how close the lines are to the text
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    # --- Building the Story ---
    story = []

    # 1. Add Masthead
    story.append(KeepInFrame(usable_width, masthead_h, [Paragraph("FINANCIAL TIMES", masthead_style)], mode='shrink', vAlign='MIDDLE'))
    story.append(FrameBreak())
    
    story.append(dateline_table)
    story.append(FrameBreak())
    
    # 2. Add Headline (Inside KeepInFrame to handle dynamic length)
    story.append(Paragraph(title.upper(), headline_style))
    story.append(FrameBreak())
    # IMPORTANT: Tell ReportLab that once these frames are full/finished, 
    # the NEXT page created must use the 'FollowingPages' template.
    story.append(NextPageTemplate('FollowingPages'))

    # 3. Add Body Content
    # ReportLab will automatically flow this into 'first_left', then 'first_right', 
    # then jump to a new page using the 'FollowingPages' template.
    for para in paragraphs:
        if para.startswith("IMG_URL:"):
            img_url = para[len("IMG_URL:"):].strip()
            
            try:
                story.append(Spacer(1, 3 * mm))
                img = image_from_url(img_url, column_width - margin)
                story.append(img)
                story.append(Spacer(1, 3 * mm))
            except Exception as e:
                print(f"Failed to load image from {img_url}: {e}")

        else:
            story.append(Paragraph(para, body_style))

    doc.build(story)


def image_from_url(url, column_width):
    response = requests.get(url, timeout=10)
    response.raise_for_status()

    img = PILImage.open(BytesIO(response.content))
    img.load()

    # Detect transparency
    has_transparency = False

    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        has_transparency = alpha.getextrema()[0] < 255

    elif img.mode == "P" and "transparency" in img.info:
        has_transparency = True

    # If transparent → flatten → grayscale
    if has_transparency:
        print("Image has transparency, converting to grayscale with white background.")
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        bg = PILImage.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))

        # img = bg.convert("L")  # grayscale

    else:
        # No transparency → keep original colors
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="PNG")  # PNG is safest for ReportLab
    buf.seek(0)
    # Preserve aspect ratio
    aspect = img.height / img.width
    rl_img = Image(
        buf,
        width=column_width,
        height=column_width * aspect
    )

    return rl_img
# -----------------------------
# HTML parsers
# -----------------------------
class ArchiveLinkParser(HTMLParser):
    HASH_RE = re.compile(r"^https://archive\.ph/[A-Za-z0-9]{4,6}$")

    def __init__(self):
        super().__init__()
        self.archive_url = None

    def handle_starttag(self, tag, attrs):
        if tag != "a" or self.archive_url is not None:
            return

        for k, v in attrs:
            if k == "href" and self.HASH_RE.match(v):
                self.archive_url = v
                return


class ArticleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tag_stack = []
        self.articles = []
        self.is_published_context = False
        self.text = ''

    def handle_starttag(self, tag, attrs):
        VOID_TAGS = {
            "img", "br", "hr", "input", "meta", "link",
            "source", "track", "area", "base", "col", "embed", "wbr"
        }
        if tag not in VOID_TAGS:
            self.tag_stack.append(tag)
        
        if self.tag_stack[-2:] == ["figure", "picture"] and tag == 'img':
            src = None
            for attr, value in attrs:
                if attr == "src":
                    src = value
                    break
            
            if src:
                self.articles.append("IMG_URL:" + src)

        if tag == "br" and self.text != '':
            self.articles.append(self.text)
            self.text = ''
        
        if tag == "time":
            for attr, value in attrs:
                if attr == "datetime" and self.is_published_context:
                    self.published = value
                    self.is_published_context = False
        

    def handle_endtag(self, tag):
        if self.tag_stack[-2:] == ["article", "p"]:
            self.articles.append(self.text)
            self.text = ''
                
        if self.tag_stack:
            self.tag_stack.pop()


    def handle_data(self, data):
        if any(a == "article" and b == "p" for a, b in zip(self.tag_stack, self.tag_stack[1:])):
            if ('em' not in self.tag_stack):
                text = data.strip()
                if text:
                    self.text += " " + text

        
        if "Published" in data:
            self.is_published_context = True




# -----------------------------
# Helpers
# -----------------------------
def load_seen_articles():
    if not os.path.exists(SEEN_FILE):
        return set()

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception:
        return set()


def save_seen_articles(new_urls):
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        for url in new_urls:
            f.write(url + "\n")


def fetch_html(url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(2.5, 5.0))  # polite delay
            print(url)
            req = urllib.request.Request(
                url,
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="ignore")

        except HTTPError as e:
            if e.code == 429:
                wait = (attempt + 1) * 10
                print(f"429 received, waiting {wait}s before retry...")
                time.sleep(wait)
                continue
            raise

    raise RuntimeError("Too many 429 responses")



def find_existing_archive(original_url):
    lookup_url = "https://archive.ph/" + original_url
    html = fetch_html(lookup_url)

    parser = ArchiveLinkParser()
    parser.feed(html)
    return parser.archive_url


def extract_articles(html):
    parser = ArticleHTMLParser()
    parser.feed(html)
    return parser.articles, parser.published


# -----------------------------
# Main logic
# -----------------------------
def fetch_new_articles(urls):

    for url, title in urls:
        try:
            html = fetch_html_from_playwrite(url)
            """
                # Save the HTML for debugging / backup
                safe_name = url.split("/")[-1][:50]
                html_file = os.path.join(OUTPUT_DIR, f"{safe_name}.html")
                with open(html_file, "w", encoding="utf-8") as f:
                    f.write(html)
            """
             
            articles, published = extract_articles(html)

            if not articles:
                print(f"No <article> content in: {url}")
                continue

            dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
            eu_dt = dt.astimezone(ZoneInfo("CET"))

            filename = f"articles/{eu_dt.strftime('%y%m%d%H%M%S')}{random.randint(0, 9999):04d}.pdf"
                # Save text as before
            generate_newspaper_pdf(
                    filename=filename,
                    title=title,
                    paragraphs=articles,
                    published=published
                )
                
            if os.path.exists(filename):
                upload_file(filename, FOLDER_ID)
                save_seen_articles([url])
                os.remove(filename)
                        
                
                """
                out_file = os.path.join(OUTPUT_DIR, f"{safe_name}.txt")
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(title + "\n")
                    f.write(url + "\n")
                    f.write(archive_url + "\n")
                    f.write(datetime.now(UTC).isoformat() + "\n\n")
                    for i, block in enumerate(articles, 1):
                        f.write(block.strip() + "\n\n")
                """

        except Exception as e:
            print(f"Error processing {url}: {e}")

    return


def get_drive_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                raise Exception("No valid creds")
        except Exception:
            # Token is invalid or revoked → force re-auth
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)

            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    return build('drive', 'v3', credentials=creds)

"""

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )

    service = build("drive", "v3", credentials=creds)
    return service

"""

def upload_file(file_path, folder_id):
    service = get_drive_service()

    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }

    media = MediaFileUpload(file_path, resumable=True)

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()

    print("Uploaded file ID:", file.get('id'))

def cleanup_old_files(folder_id, days=7):
    service = get_drive_service()

    # Time threshold (timezone-aware)
    threshold = datetime.now(timezone.utc) - timedelta(days=days)

    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, createdTime)"
    ).execute()

    files = results.get('files', [])

    for file in files:
        created_time = datetime.fromisoformat(file['createdTime'])
        if created_time < threshold:
            print(f"Deleting {file['name']} (created {file['createdTime']})")
            service.files().delete(fileId=file['id']).execute()

EXT_ID = "lkbebcjgcmobigpeffafkodonchffocl"
OPTIONS_URL = f"chrome-extension://{EXT_ID}/options/options.html"

def fetch_html_from_playwrite(url):
    PAGE.goto(url, wait_until="domcontentloaded")

    return PAGE.content()


PAGE = None

if __name__ == "__main__":
    new_urls = []
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    seen = load_seen_articles()

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            url = entry.get("link")
            title = entry.get("title")

            if url and url not in seen:
                new_urls.append([url, title])

    if len(new_urls):
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE,
                headless=False,  # extensions do NOT work in true headless
                args=[
                    f"--disable-extensions-except={EXT_PATH}",
                    f"--load-extension={EXT_PATH}",
                ]
            )

            time.sleep(3)
            
            PAGE = context.new_page()

            fetch_new_articles(new_urls)
        #print(f"Fetched {len(new_articles)} new articles.")
        #upload_file('articles/test.pdf', FOLDER_ID)

            cleanup_old_files(FOLDER_ID, days=3)
            
            context.close()
    
