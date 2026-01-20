import os
import re
import threading
import requests
import feedparser
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
from github import Github, GithubException
from urllib.parse import unquote, urlparse, parse_qs

# --- 환경 변수 로드 ---
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TISTORY_RSS_URL = os.getenv("TISTORY_RSS_URL")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

REPO_LOCAL_PATH = "./temp_staging_area"
client = OpenAI(api_key=OPENAI_API_KEY)

# GUI 체크
GUI_AVAILABLE = False
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

class BlogBackupCore:
    def __init__(self):
        if not GITHUB_TOKEN or not GITHUB_REPO_NAME:
            raise ValueError(".env 파일 설정을 확인해주세요.")

    def get_rss_posts(self):
        print(f"RSS 로딩: {TISTORY_RSS_URL}")
        feed = feedparser.parse(TISTORY_RSS_URL)
        posts = []
        for entry in feed.entries:
            try:
                dt = datetime(*entry.published_parsed[:6])
                date_str = dt.strftime("%Y-%m-%d")
            except:
                date_str = datetime.now().strftime("%Y-%m-%d")
            posts.append({"title": entry.title, "link": entry.link, "date": date_str})
        return posts

    def process_backup(self, post_data, log_callback=print):
        try:
            log_callback(f"🚀 작업 시작: {post_data['title']}")
            
            res = requests.get(post_data['link'])
            soup = BeautifulSoup(res.text, 'html.parser')
            
            content_div = soup.select_one('.tt_article_useless_p_margin') or \
                          soup.select_one('#article-view') or \
                          soup.select_one('div[class*="article"]')

            if not content_div:
                log_callback("⚠️ 본문 영역을 찾지 못했습니다.")
                return

            # 날짜 정밀 추출
            final_date = post_data['date']
            date_element = soup.select_one('.info_post')
            if date_element:
                match = re.search(r'(\d{4}\.\s?\d{1,2}\.\s?\d{1,2})', date_element.text)
                if match:
                    raw_date = match.group(1).replace(" ", "")
                    final_date = datetime.strptime(raw_date, "%Y.%m.%d").strftime("%Y-%m-%d")

            # [수정됨] Slug(파일명) 생성 프롬프트 개선
            log_callback("🤖 AI: 파일명(Slug) 생성 중...")
            slug_response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "system", 
                    "content": "You are a slug generator. Output ONLY the English kebab-case string. Do not output any explanation, punctuation, or dates."
                }, {
                    "role": "user", 
                    "content": f"Convert this title to a strict English kebab-case slug: {post_data['title']}"
                }]
            )
            slug = slug_response.choices[0].message.content.strip()
            # 혹시 모를 공백/특수문자 한번 더 제거
            slug = re.sub(r'[^a-zA-Z0-9-]', '', slug)
            
            # [수정됨] 이미지 URL 정제
            log_callback("🔗 이미지 링크 변환 중 (다운로드 안함)...")
            processed_html = self.clean_image_urls(str(content_div))

            # [수정됨] Markdown 변환 (카테고리 규칙 적용)
            log_callback("📝 AI: Markdown 변환 및 카테고리 분류 중...")
            md_content = self.convert_to_markdown(processed_html, post_data['title'], final_date)

            # 파일 저장
            yy_mm_dd = datetime.strptime(final_date, "%Y-%m-%d").strftime("%y-%m-%d")
            md_filename = f"{yy_mm_dd}-{slug}.md"
            md_file_path = os.path.join(REPO_LOCAL_PATH, "_posts", md_filename)
            os.makedirs(os.path.dirname(md_file_path), exist_ok=True)
            
            with open(md_file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            
            log_callback(f"💾 파일 생성: {md_filename}")

            # 업로드
            log_callback("☁️  GitHub 업로드 중...")
            self.upload_via_api(f"Add post: {post_data['title']}", log_callback)
            log_callback("✅ 완료!")

        except Exception as e:
            log_callback(f"❌ 오류: {e}")
            import traceback
            traceback.print_exc()

    def clean_image_urls(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        images = soup.find_all('img')
        for img in images:
            original_src = img.get('src')
            if not original_src: continue
            
            if img.has_attr('srcset'): del img['srcset']
            if img.has_attr('width'): del img['width']
            if img.has_attr('height'): del img['height']
            if img.has_attr('style'): del img['style']
            
            if "fname=" in original_src:
                try:
                    parsed_url = urlparse(original_src)
                    query_params = parse_qs(parsed_url.query)
                    if 'fname' in query_params:
                        real_url = unquote(query_params['fname'][0])
                        img['src'] = real_url
                except: pass
        return str(soup)

    def convert_to_markdown(self, html_content, title, date):
        # AI에게 "HTML 본문 안에 있는 제목 정보는 무시하라"고 강제하는 프롬프트
        system_prompt = f"""
        You are a specialized tool that converts Tistory HTML to Jekyll Markdown.

        ================================================================================
        🚨 CRITICAL INSTRUCTION: FRONTMATTER TITLE 🚨
        The `title` field in the Frontmatter MUST be: "{title}"
        
        Rules for Title:
        1. Use the string provided above verbatim.
        2. **IGNORE** any <h1>, <h2>, or title text found inside the input HTML.
        3. Even if the HTML content starts with a different header, DO NOT use it as the title.
        4. Preserve exact capitalization and spacing of the string above.
        ================================================================================

        ### Category Selection Rules (Priority Order):
        1. **SWING**: If title/content contains 'SWING' (case-insensitive).
        2. **Writeup**: If content is about CTF, Wargames, security challenges.
        3. **Self-study**: If technical study content but NOT 'SWING' or 'Writeup'.
        4. **+**: If none of the above.

        ### Output Format (Strict YAML Frontmatter):
        ---
        layout: post
        title: "{title}"
        categories: [Category Name]
        tags: [Infer 3-5 lowercase keywords]
        last_modified_at: {date}
        ---

        (Converted Markdown Body...)

        ### Body Rules:
        1. **Images:** Keep `src` exactly as input. Use `![Alt](url)`.
        2. **Code:** Use fenced code blocks (```language).
        3. **Language:** Preserve Korean.
        4. **Clean:** Remove `div`, `span`, `style` tags.
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": html_content}
            ],
            temperature=0.0 # 창의성 0 (지시사항 엄수)
        )
        return response.choices[0].message.content

    def upload_via_api(self, commit_msg, log_callback):
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        branch = "backup"
        
        try: repo.get_branch(branch)
        except:
            sb = repo.get_branch("main")
            repo.create_git_ref(f"refs/heads/{branch}", sb.commit.sha)

        for root, _, files in os.walk(REPO_LOCAL_PATH):
            for file in files:
                if file.startswith('.'): continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, REPO_LOCAL_PATH)
                
                with open(full_path, "rb") as f: content = f.read()
                
                try:
                    contents = repo.get_contents(rel_path, ref=branch)
                    repo.update_file(contents.path, commit_msg, content, contents.sha, branch=branch)
                    log_callback(f"UPDATE: {rel_path}")
                except:
                    repo.create_file(rel_path, commit_msg, content, branch=branch)
                    log_callback(f"CREATE: {rel_path}")

        try:
            pulls = repo.get_pulls(state='open', head=f"{repo.owner.login}:{branch}", base='main')
            if pulls.totalCount == 0:
                pr = repo.create_pull(title=f"[Auto] {commit_msg}", body="Auto-generated", head=branch, base="main")
                log_callback(f"🚀 PR 생성: {pr.html_url}")
            else:
                log_callback(f"ℹ️ PR 이미 존재: {pulls[0].html_url}")
        except Exception as e:
            log_callback(f"PR 스킵: {e}")

if __name__ == "__main__":
    if GUI_AVAILABLE:
        class TistoryGUI:
            def __init__(self, root):
                self.core = BlogBackupCore()
                self.root = root
                self.root.title("Tistory Agent (Fixed)")
                self.root.geometry("600x600")
                tk.Button(root, text="목록 불러오기", command=self.load).pack(pady=5)
                self.tree = ttk.Treeview(root, columns=("d","t"), show="headings"); self.tree.pack(fill="both", expand=True)
                self.tree.heading("d", text="Date"); self.tree.heading("t", text="Title")
                self.btn = tk.Button(root, text="실행", command=self.run); self.btn.pack(fill="x")
                self.log_t = scrolledtext.ScrolledText(root, height=10); self.log_t.pack(fill="both")
                self.posts=[]
            def log(self, m): self.log_t.insert(tk.END, m+"\n"); self.log_t.see(tk.END)
            def load(self):
                self.posts=self.core.get_rss_posts()
                self.tree.delete(*self.tree.get_children())
                for p in self.posts: self.tree.insert("","end",values=(p['date'],p['title']))
            def run(self):
                sel=self.tree.selection()
                if sel: threading.Thread(target=self.core.process_backup, args=(self.posts[self.tree.index(sel[0])], self.log)).start()

        root = tk.Tk()
        app = TistoryGUI(root)
        root.mainloop()
    else:
        c = BlogBackupCore()
        ps = c.get_rss_posts()
        for i,p in enumerate(ps): print(f"{i} {p['title']}")
        idx = int(input("번호: "))
        c.process_backup(ps[idx])