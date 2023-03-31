import logging
import os
import sys
from git import Git, Repo
from uuid import uuid4

from weasyprint import HTML, urls, CSS
from bs4 import BeautifulSoup
import re
from weasyprint.text.fonts import FontConfiguration

from mkpdfs_mkdocs.utils import gen_address
from .utils import is_external
from mkpdfs_mkdocs.preprocessor import get_separate as prep_separate, get_combined as prep_combined

log = logging.getLogger(__name__)


class Generator(object):

    def __init__(self):
        self.config = None
        self.design = None
        self.mkdconfig = None
        self.nav = None
        self.title = None
        self.logger = logging.getLogger('mkdocs.mkpdfs')
        self.generate = True
        self._articles = {}
        self._page_order = []
        self._base_urls = {}
        self._toc = None
        self.html = BeautifulSoup('<html><head></head>\
        <body></body></html>',
                                  'html.parser')
        self.dir = os.path.dirname(os.path.realpath(__file__))
        self.design = os.path.join(self.dir, 'design/report.css')
    
    def get_repo_name(self):
        repo = Repo()
        remote_url = repo.remotes[0].config_reader.get("url")  
        return os.path.splitext(os.path.basename(remote_url))[0]
  
    def get_latest_version(self):
        """
        Function to get the latest tag from the git repository which matches
        the configured regex for the version tag format.
        :return: String with the highest semver tag, returns "unknown" if not found.
        """
        repo = Repo()
        g = Git()
        tags = sorted(repo.tags, key=lambda t: t.commit.committed_datetime)
        if len(tags) > 0:
            latest_tag = str(tags[-1]).split("v")[-1]
            #return '{} - {}'.format(tags[-1], g.log(n=1)[7:16])
            return f"Version {latest_tag}"
        else:
            return "Version 1.0"


    def set_config(self, local, config):
        self.config = local
        if self.config['design']:
            css_file = os.path.join(os.getcwd(), self.config['design'])
            if not os.path.isfile(css_file):
                sys.exit('The file {} specified for design has not \
                been found.'.format(css_file))
            self.design = css_file
        self.title = config['site_name']
        self.config['copyright'] = 'CC-BY-SA\
        ' if not config['copyright'] else config['copyright']
        self.config['version_tag'] = self.config['version_tag'] if self.config['version_tag'] else self.get_latest_version() 
        self.config['project_name'] = self.config['project_name'] if self.config['project_name'] else self.get_repo_name() 
        self.mkdconfig = config

    def write(self):
        if not self.generate:
            self.logger.log(msg='Unable to generate the PDF Version (See Mkpdfs doc)',
                            level=logging.WARNING, )
            return
        self.gen_articles()
        font_config = FontConfiguration()
        self.add_head()
        pdf_path = os.path.join(self.mkdconfig['site_dir'],
                                self.config['output_path'])
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        html = HTML(string=str(self.html)).write_pdf(pdf_path,
                                                     font_config=font_config)
        self.logger.log(msg='The PDF version of the documentation has been generated.', level=logging.INFO, )

    def add_nav(self, nav):
        self.nav = nav
        for page in nav:
            page.is_toplevel = True
            page.is_standalone =  len(self.nav) == 1
            self.add_to_order(page)

    def add_to_order(self, page):
        page.is_toplevel = page.is_toplevel if hasattr(page, 'is_toplevel') else False 
        if page.is_page and page.meta and 'pdf' in page.meta and not page.meta['pdf']:
            return
        if page.is_page:
            if page.is_toplevel:
                uuid = str(uuid4())
                title = self.html.new_tag('h1',
                                          id='{}-title'.format(uuid),
                                          **{'class': 'section_title'}
                                          )
                try:
                    title.append(page.title)
                except ValueError:
                    return
                self._page_order.append(uuid)
                if page.is_standalone:
                    article = self.html.new_tag('article',
                                            id='{}'.format(uuid),
                                            **{'class': 'standalone'}
                                            )
                else:
                    article = self.html.new_tag('article',
                        id='{}'.format(uuid),
                        **{'class': 'chapter'}
                        )
                article.append(title)
                self._articles[uuid] = article
            self._page_order.append(page.file.url)                        
        elif page.children:
            uuid = str(uuid4())
            self._page_order.append(uuid)
            title = self.html.new_tag('h1',
                                      id='{}-title'.format(uuid),
                                      **{'class': 'section_title'}
                                      )
            title.append(page.title)
            article = self.html.new_tag('article',
                                        id='{}'.format(uuid),
                                        **{'class': 'chapter'}
                                        )
            article.append(title)
            self._articles[uuid] = article
            for child in page.children:
                self.add_to_order(child)


    def remove_from_order(self, item):
        return

    def add_article(self, content, page, base_url):
        if not self.generate:
            return None
        self._base_urls[page.file.url] = base_url
        soup = BeautifulSoup(content, 'html.parser')
        url = page.url.split('.')[0]
        article = soup.find('article')
        if not article:
            article = self.html.new_tag('article')
            eld = soup.find('div', **{'role': 'main'})
            article.append(eld)
            article.div['class'] = article.div['role'] = None

        if not article:
            self.generate = False
            return None
        article = prep_combined(article, base_url, page.file.url)
        if page.meta and 'pdf' in page.meta and not page.meta['pdf']:
            return self.get_path_to_pdf(page.file.dest_path)
        self._articles[page.file.url] = article
        return self.get_path_to_pdf(page.file.dest_path)

    def add_head(self):
        lines = ['<title>{}</title>'.format(self.title)]
        for key, val in (
                ("author", self.config['author'] or self.mkdconfig['site_author']),
                ("description", self.mkdconfig['site_description']),
        ):
            if val:
                lines.append('<meta name="{}" content="{}">'.format(key, val))
        for css in (self.design,):
            if css:
                css_tmpl = '<link rel="stylesheet" href="{}" type="text/css">'
                lines.append(css_tmpl.format(urls.path2url(css)))
        head = BeautifulSoup('\n'.join(lines), 'html5lib')
        self.html.head.clear()
        self.html.head.insert(0, head)

    def get_path_to_pdf(self, start):
        pdf_split = os.path.split(self.config['output_path'])
        start_dir = os.path.split(start)[0]
        return os.path.join(os.path.relpath(pdf_split[0],
                                            start_dir), pdf_split[1])

    def create_tocs(self):
        title = self.html.new_tag('h1', id='toc-title')
        title.insert(0, self.config['toc_title'])
        self._toc = self.html.new_tag('article', id='contents')
        self._toc.insert(0, title)
        for n in self.nav:
            if n.is_page and n.meta and 'pdf' in n.meta \
                    and not n.meta['pdf']:
                continue
            if hasattr(n, 'url') and is_external(n.url):
                # Skip toc generation for external links
                continue
            h3 = self.html.new_tag('p')
            name = self.html.new_tag('strong')
            name.insert(0, n.title)
            h3.append(name)
            self._toc.append(h3)
            self.toc_depth = 1
            if n.is_page:
                ptoc = self._gen_toc_page(n.file.url, n.toc)
                self._toc.append(ptoc)
            else:
                self._gen_toc_section(n)
                
    def add_tocs(self):
        self.html.body.append(self._toc)

    def add_cover(self):
        a = self.html.new_tag('article', id='doc-cover')
        title = self.html.new_tag('h1', id='doc-title')
        version = self.html.new_tag('p', id='version')
        if self.config['version_tag']:
            version.insert(0, self.config['version_tag'])
        title.append(version)
        title.insert(0, self.title)
        a.insert(0, title)
        a.append(gen_address(self.config))
        self.html.body.append(a)

    def gen_articles(self):
        if  self.config['toc_numbered']:
            headings = {'h{}'.format(i):0 for i in range(1, 10)}
            names = {'h{}'.format(level):'h{}'.format(level+1) for level in range(1, 10)}
            indeces = {'h{}'.format(level):(2*level-3) for level in range(2, self.config['toc_depth']+1)}
        for url in self._page_order:
            if url in self._articles:
                # insert numbers if config says so
                if  self.config['toc_numbered']:
                    soup = BeautifulSoup(str(self._articles[url]), 'html.parser')
                    tree = [soup.find('h1')]
                    tree += tree[0].find_next_siblings()
                    if  len(tree) == 1:
                        # a new chapter starts -> reset all counters
                        counters = {'h{}'.format(i):0 for i in range(1, self.config['toc_depth']+1)}
                        #counters = {'h{}'.format(i):0 for i in range(1, 10)}
                    else:
                        while len(tree) > 0:
                            tag = tree.pop(0)
                            if  tag.name in counters:
                                # reset section counters
                                level = int(tag.name.split('h')[-1])
                                reset_counters = {'h{}'.format(i):0 for i in range(level+1, self.config['toc_depth']+1)}
                                counters.update(reset_counters) 
                                counters[tag.name] += 1 
                                if tag.name == 'h1':
                                    number = str(counters[tag.name])
                                    tag.insert(0, number)
                                    tag.insert(-1, ' ')
                                else:
                                    number = number[:indeces[tag.name]]
                                    number += '.{}'.format(counters[tag.name])
                                    tag.insert(0, number)
                                    tag.insert(-1, ' ')
                                tag.name = names[tag.name]
                            elif tag.name in headings:
                                tag.name = names[tag.name]
                            self._articles[url] = soup.find('article')
                            
        # put everything together
        self.add_cover()
        self.create_tocs()
        if self.config['toc_position'] == 'pre':
            self.add_tocs()
        for url in self._page_order:
            if url in self._articles:
                self.html.body.append(self._articles[url])
        if self.config['toc_position'] == 'post':
            self.add_tocs()

    def get_path_to_pdf(self, start):
        pdf_split = os.path.split(self.config['output_path'])
        start_dir = os.path.split(start)[0] if os.path.split(start)[0] else '.'
        return os.path.join(os.path.relpath(pdf_split[0], start_dir),
                            pdf_split[1])

    def _gen_toc_section(self,  section):
        if section.children:  # External Links do not have children
            for p in section.children:
                if p.is_page and p.meta and 'pdf' \
                        in p.meta and not p.meta['pdf']:
                    continue
                if not hasattr(p, 'file'):
                    # Skip external links
                    continue                    
                stoc = self._gen_toc_for_section(p.file.url, p)
                child = self.html.new_tag('div')
                child.append(stoc)
                self._toc.append(child)

    def _gen_children(self, url, children, soup=None):
        ul = self.html.new_tag('ul')
        for child in children:
            #if self.config['toc_numbered'] and soup:
            print(child.title)
            t = soup.find('h{}'.format(child.level+1), string=child.title)
            if t:
                child.title = t.text
            a = self.html.new_tag('a', href=child.url)
            a.insert(0, child.title)
            li = self.html.new_tag('li')
            li.append(a)
            if child.children and child.level < self.config['toc_depth']:
                sub = self._gen_children(url, child.children, soup)
                li.append(sub)
            ul.append(li)
        return ul


    def _gen_toc_for_section(self,  url, p):
        div = self.html.new_tag('div')
        menu = self.html.new_tag('div')
        h4 = self.html.new_tag('li')
        a = self.html.new_tag('a', href='#')
        #if self.config['toc_numbered']:
        soup = BeautifulSoup(str(self._articles[url]), 'html.parser')
        t = soup.find('h2', string=re.compile(p.title))
        if t:
            p.title = t.text            
        a.insert(0, p.title)
        #self.toc_depth = 1
        h4.append(a)
        menu.append(h4)
        ul = self.html.new_tag('div')
        if p.toc:
            for child in p.toc.items:
                #self.toc_depth = 2
                #if self.config['toc_numbered']:
                #t = soup.find('h{}'.format(child.level+1), string=re.compile(child.title))
                #t = soup.find(string=re.compile(child.title))
                if t:
                    child.title = t.text
                a = self.html.new_tag('a', href=child.url)
                a.insert(0, child.title)
                li = self.html.new_tag('li')
                li.append(a)
                if child.title == p.title:
                    li = self.html.new_tag('div')
                    #self.toc_depth = 1
                if child.children:
                    if child.level < self.config['toc_depth']:
                        sub = self._gen_children(url, child.children, soup)
                        li.append(sub)
                ul.append(li)
            if len(p.toc.items) > 0:
                menu.append(ul)
        div.append(menu)
        div = prep_combined(div, self._base_urls[url], url)
        return div.find('div')

    def _gen_toc_page(self, url, toc):
        div = self.html.new_tag('div')
        menu = self.html.new_tag('div')
        #self.toc_depth = 1        
        soup = BeautifulSoup(str(self._articles[url]), 'html.parser')
        for item in toc.items:
            li = self.html.new_tag('li')
            a = self.html.new_tag('a', href=item.url)
            t = soup.find('h{}'.format(item.level+1), string=re.compile(item.title))
            if t:
                item.title = t.text
                a.append(item.title)
                li.append(a)
                menu.append(li)
                #self.toc_depth = 2
                if item.children:
                    if item.level < self.config['toc_depth']:
                        child = self._gen_children( url, item.children, soup)
                        menu.append(child)
            
        div.append(menu)
        div = prep_combined(div, self._base_urls[url], url)
        return div.find('div')
