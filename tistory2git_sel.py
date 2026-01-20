import os
import re
import threading
import html
import time
import shutil
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
from github import Github, GithubException
from urllib.parse import unquote, urlparse, parse_qs

# Selenium 관련
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- 환경 변수 로드 ---
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
TISTORY_BLOG_NAME = os.getenv("TISTORY_BLOG_NAME")
TISTORY_ID = os.getenv("TISTORY_ID")
TISTORY_PW = os.getenv("TISTORY_PW")

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
        if not GITHUB_TOKEN or not TISTORY_BLOG_NAME:
            raise ValueError(".env 파일 설정을 확인해주세요 (TISTORY_BLOG_NAME 필수).")
        
        self.options = webdriver.ChromeOptions()
        self.options.add_argument("--disable-gpu")
        self.options.add_argument("--no-sandbox")
        # self.options.add_argument("--headless") 
        self.driver = None

    def start_browser(self):
        if self.driver is not None: return
        print("🌐 브라우저를 실행합니다...")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=self.options)
        
        login_url = "https://www.tistory.com/auth/login"
        self.driver.get(login_url)
        time.sleep(1)

        # 자동 로그인 시도
        if TISTORY_ID and TISTORY_PW:
            print("🔑 자동 로그인을 시도합니다...")
            try:
                kakao_login_btn = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn_login.link_kakao_id"))
                )
                kakao_login_btn.click()
                
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.NAME, "email")))
                
                email_input = self.driver.find_element(By.NAME, "email")
                email_input.clear()
                email_input.send_keys(TISTORY_ID)
                
                pw_input = self.driver.find_element(By.NAME, "password")
                pw_input.clear()
                pw_input.send_keys(TISTORY_PW)
                pw_input.send_keys(Keys.RETURN)
                
                print("⏳ 로그인 정보 전송. 접속 대기...")
            except Exception as e:
                print(f"⚠️ 자동 로그인 실패 (직접 하세요): {e}")

        # 로그인 완료 대기
        try:
            WebDriverWait(self.driver, 300).until(
                lambda d: "tistory.com/manage" in d.current_url or "tistory.com/feed" in d.current_url
            )
            print("✅ 로그인 성공!")
        except:
            print("❌ 로그인 시간 초과.")
            self.driver.quit()
            self.driver = None

    def get_post_list(self):
        """관리자 페이지 글 목록 전체 스크래핑 (페이지 번호 기반 순차 이동)"""
        if not self.driver: self.start_browser()
        
        # 1. 관리자 페이지 접속
        manage_url = f"https://{TISTORY_BLOG_NAME}.tistory.com/manage/posts"
        self.driver.get(manage_url)
        time.sleep(2)

        all_posts = []
        current_page = 1 # 1페이지부터 시작

        while True:
            print(f"📄 {current_page}페이지 스캔 중... (현재 수집: {len(all_posts)}개)")
            
            # 페이지 로딩 대기 (게시글 목록이 뜰 때까지)
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "ul.list_post"))
                )
            except:
                print("⚠️ 게시글 목록 로딩 시간 초과")
                break

            # --- 현재 페이지 게시글 파싱 ---
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            items = soup.select('ul.list_post li')
            
            if not items:
                print("🏁 게시글이 더 이상 없습니다.")
                break

            for item in items:
                try:
                    link_tag = item.select_one('a.link_cont') or item.select_one('a.link_title')
                    if not link_tag: continue
                    
                    title = link_tag.text.strip()
                    href = link_tag['href']
                    if href.startswith('/'):
                        href = f"https://{TISTORY_BLOG_NAME}.tistory.com{href}"

                    # 상태 추출
                    if item.select_one('.ico_private'): status = "🔒비공개"
                    elif item.select_one('.ico_secret'): status = "🛡️보호"
                    else: status = "✅공개"
                    
                    # 날짜 추출
                    date_str = datetime.now().strftime("%Y-%m-%d")
                    info_spans = item.select('.txt_info')
                    for span in info_spans:
                        match = re.search(r'\d{4}-\d{2}-\d{2}', span.text)
                        if match:
                            date_str = match.group()
                            break
                    
                    all_posts.append({
                        "title": title,
                        "url": href,
                        "date": date_str,
                        "status": status
                    })
                except: pass
            
            # --- [핵심 수정] 다음 페이지(current_page + 1) 링크 찾기 ---
            next_page = current_page + 1
            found_next_link = False
            
            try:
                # 1. 모든 페이징 링크(숫자, 다음 버튼 등)를 가져옴
                paging_links = self.driver.find_elements(By.CSS_SELECTOR, ".list_paging a, .link_paging")
                
                target_link = None
                
                # 2. 링크들을 하나씩 검사해서 href에 "page={next_page}"가 있는지 확인
                for link in paging_links:
                    href = link.get_attribute("href")
                    if href and f"page={next_page}" in href:
                        # "page=15"를 찾는데 "page=151"이 걸리지 않도록 정규식 검사 권장되나,
                        # 티스토리 URL 구조상 &page=값& 형태이므로 단순 포함 여부도 꽤 정확함.
                        # 더 정확히 하려면:
                        if re.search(f"[?&]page={next_page}(&|$)", href):
                            target_link = link
                            break
                
                # 3. 목표 링크 클릭
                if target_link:
                    # 화면 스크롤 (버튼이 가려져 있을 수 있음)
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_link)
                    time.sleep(0.5)
                    
                    # JS로 강제 클릭 (가장 확실함)
                    self.driver.execute_script("arguments[0].click();", target_link)
                    
                    print(f"➡️  {next_page}페이지로 이동합니다...")
                    time.sleep(2.5) # 페이지 로딩 대기
                    current_page += 1
                    found_next_link = True
                else:
                    print(f"🏁 {next_page}페이지 링크를 찾을 수 없습니다. (마지막 페이지)")
                    break
                    
            except Exception as e:
                print(f"❌ 페이지 이동 중 에러 발생: {e}")
                break
                
            if not found_next_link:
                break

        print(f"📊 총 {len(all_posts)}개의 글을 수집했습니다.")
        return all_posts

    def process_batch_backup(self, selected_posts, log_callback=print):
        if os.path.exists(REPO_LOCAL_PATH):
            shutil.rmtree(REPO_LOCAL_PATH)
        os.makedirs(REPO_LOCAL_PATH, exist_ok=True)
        
        processed_titles = []
        total_count = len(selected_posts)
        log_callback(f"📦 총 {total_count}개 글 작업 시작.")

        for idx, post_data in enumerate(selected_posts):
            try:
                log_callback(f"[{idx+1}/{total_count}] 변환: {post_data['title']}")
                self.save_post_to_local(post_data, log_callback)
                processed_titles.append(post_data['title'])
            except Exception as e:
                log_callback(f"❌ 실패 ({post_data['title']}): {e}")

        if not processed_titles:
            log_callback("⚠️ 성공한 글이 없습니다.")
            return

        log_callback(f"☁️  GitHub 업로드 중... ({len(processed_titles)}개)")
        summary = ", ".join(processed_titles)
        if len(summary) > 50: summary = summary[:50] + "..."
        commit_msg = f"Add {len(processed_titles)} posts: {summary}"
        
        self.upload_via_api(commit_msg, log_callback)
        log_callback("🎉 작업 완료!")

    def save_post_to_local(self, post_data, log_callback):
        if not self.driver: self.start_browser()
        self.driver.get(post_data['url'])
        time.sleep(1.5)
        
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        
        # 본문 영역 찾기 (다양한 스킨 대응)
        content_div = soup.select_one('.tt_article_useless_p_margin') or \
                      soup.select_one('#article-view') or \
                      soup.select_one('.contents_style') or \
                      soup.select_one('.area_view') or \
                      soup.select_one('div[class*="article"]')

        if not content_div:
            raise Exception("본문 영역 없음")

        # AI Slug
        slug_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "You are a slug generator. Output ONLY English kebab-case string."},
                      {"role": "user", "content": f"Convert: {post_data['title']}"}]
        )
        slug = re.sub(r'[^a-zA-Z0-9-]', '', slug_resp.choices[0].message.content.strip())
        
        # 이미지 처리
        processed_html = self.clean_image_urls(str(content_div))

        # Markdown 변환
        md_content = self.convert_to_markdown(processed_html, post_data['title'], post_data['date'])
        md_content = html.unescape(md_content)

        # 저장
        md_file = f"{post_data['date']}-{slug}.md"
        md_path = os.path.join(REPO_LOCAL_PATH, "_posts", md_file)
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f: f.write(md_content)

    def clean_image_urls(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        for img in soup.find_all('img'):
            src = img.get('src')
            if not src: continue
            for a in ['srcset', 'width', 'height', 'style', 'onerror']:
                if img.has_attr(a): del img[a]
            
            if "fname=" in src:
                try:
                    q = parse_qs(urlparse(src).query)
                    if 'fname' in q: img['src'] = unquote(q['fname'][0])
                except: pass
        return str(soup)

    def convert_to_markdown(self, html_content, title, date):
        sys_prompt = f"""
        You are a specialized tool converting Tistory HTML to Jekyll Markdown.
        
        ### CRITICAL: TITLE
        - YAML Frontmatter `title`: "{title}"
        - Ignore HTML headers. Preserve capitalization.

        ### Categories:
        1. SWING (case-insensitive)
        2. Writeup (CTF/Wargame)
        3. Self-study (Study)
        4. + (Else)

        ### Output:
        ---
        layout: post
        title: "{title}"
        categories: [Category]
        tags: [Keywords]
        last_modified_at: {date}
        ---
        
        (Body...)
        """
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": html_content}],
            temperature=0.0
        )
        return resp.choices[0].message.content

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
                    c = repo.get_contents(rel_path, ref=branch)
                    repo.update_file(c.path, commit_msg, content, c.sha, branch=branch)
                    log_callback(f"UPDATE: {rel_path}")
                except:
                    repo.create_file(rel_path, commit_msg, content, branch=branch)
                    log_callback(f"CREATE: {rel_path}")

        try:
            pulls = repo.get_pulls(state='open', head=f"{repo.owner.login}:{branch}", base='main')
            if pulls.totalCount == 0:
                pr = repo.create_pull(title=f"[Auto] {commit_msg}", body="Batch Backup", head=branch, base="main")
                log_callback(f"🚀 PR 생성: {pr.html_url}")
            else:
                log_callback(f"ℹ️ PR 존재: {pulls[0].html_url}")
        except Exception as e: log_callback(f"PR 스킵: {e}")

    def __del__(self):
        if self.driver: 
            try: self.driver.quit() 
            except: pass

if __name__ == "__main__":
    if GUI_AVAILABLE:
        class TistoryGUI:
            def __init__(self, root):
                self.core = BlogBackupCore()
                self.root = root
                self.root.title("Tistory Full Backup Agent")
                self.root.geometry("800x650")
                
                tk.Button(root, text="🌐 자동 로그인 & 전체 글 스캔", command=self.load).pack(pady=5)
                
                self.tree = ttk.Treeview(root, columns=("d","s","t"), show="headings", selectmode="extended")
                self.tree.heading("d", text="Date"); self.tree.column("d", width=100)
                self.tree.heading("s", text="Status"); self.tree.column("s", width=80)
                self.tree.heading("t", text="Title"); self.tree.column("t", width=450)
                self.tree.pack(fill="both", expand=True, padx=10)
                
                sc = ttk.Scrollbar(root, orient="vertical", command=self.tree.yview)
                self.tree.configure(yscroll=sc.set)
                
                self.btn = tk.Button(root, text="🚀 선택 항목 일괄 백업 & PR", command=self.run_batch, bg="#eee", height=2)
                self.btn.pack(fill="x", padx=10, pady=5)
                
                self.log_t = scrolledtext.ScrolledText(root, height=12)
                self.log_t.pack(fill="both")
                self.posts=[]
                
            def log(self, m): 
                self.log_t.insert(tk.END, m+"\n")
                self.log_t.see(tk.END)

            def load(self):
                threading.Thread(target=self._load_thread).start()
            
            def _load_thread(self):
                self.log("브라우저 및 자동 로그인 시작...")
                try:
                    self.posts = self.core.get_post_list()
                    self.tree.delete(*self.tree.get_children())
                    for p in self.posts: 
                        self.tree.insert("","end",values=(p['date'], p['status'], p['title']))
                    self.log(f"✅ 총 {len(self.posts)}개의 글 로드 완료")
                except Exception as e:
                    self.log(f"로드 실패: {e}")
                    
            def run_batch(self):
                sel = self.tree.selection()
                if not sel: return messagebox.showwarning("!", "글을 선택해주세요.")
                
                posts = [self.posts[self.tree.index(i)] for i in sel]
                self.btn.config(state="disabled", text="작업 진행 중...")
                threading.Thread(target=self._worker, args=(posts,)).start()
                
            def _worker(self, posts):
                self.core.process_batch_backup(posts, self.log)
                self.btn.config(state="normal", text="🚀 선택 항목 일괄 백업 & PR")

        root = tk.Tk()
        app = TistoryGUI(root)
        root.mainloop()
    else:
        # CLI Fallback
        c = BlogBackupCore()
        ps = c.get_post_list()
        print("-" * 60)
        for i,p in enumerate(ps): print(f"[{i}] {p['date']} {p['title']}")
        print("-" * 60)
        idx_str = input("번호(콤마구분): ")
        idxs = [int(x) for x in idx_str.split(',')]
        c.process_batch_backup([ps[i] for i in idxs])