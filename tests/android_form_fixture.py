"""Controlled native entry form with a Spinner and radio group, modeled on the supplied recording."""
import json
import re
import time
from types import SimpleNamespace
from xml.etree import ElementTree

from defusedxml import ElementTree as SafeTree

from backend.android import extract_screen
from backend.android_app import AppSession
from backend.android_design import normalize_screens

PACKAGE = 'com.example.nativeform'


class Element:
    def __init__(self, app, attrs):
        self.app, self.attrs = app, attrs
        self.id = attrs.get('resource-id') or attrs.get('text')

    @property
    def text(self):
        if self.attrs.get('class', '').endswith('EditText'):
            return self.app.name or 'Your Name'
        return self.attrs.get('text', '')

    def get_attribute(self, key):
        if key == 'showing-hint':
            return str(not self.app.name).lower()
        return self.attrs.get(key, 'false' if key in ('password','checked','checkable') else '')

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def clear(self):
        self.app.name = ''

    def send_keys(self, value):
        self.app.name += value

    def click(self):
        key, text = self.attrs.get('resource-id', ''), self.text
        if key.endswith('/country'):
            self.app.opened = True
        elif self.app.opened:
            self.app.country, self.app.opened = 'Alpha' if self.app.bad_readback else text, False
        elif key.endswith(('/male','/female')):
            self.app.gender = text
        elif key.endswith('/submit'):
            self.app.submissions.append((self.app.name,self.app.country,self.app.gender))
            if self.app.name or self.app.accept_empty:
                self.app.view = 'products'
            else:
                self.app.error = 'Name is required'

    def find_elements(self, using, value):
        root = SafeTree.fromstring(self.app.page_source)
        owner = next(e for e in root.iter('node') if e.get('resource-id') == self.attrs.get('resource-id')
                     and (self.attrs.get('resource-id') != 'android:id/text1' or e.get('text') == self.text))
        if using == 'xpath' and 'ancestor' in value:
            parents = {child:parent for parent in root.iter() for child in parent}
            ancestors, parent = [], parents.get(owner)
            while parent is not None:
                if 'ListView' in parent.get('class', ''):
                    ancestors.append(Element(self.app,dict(parent.attrib)))
                parent = parents.get(parent)
            return ancestors
        return [Element(self.app,dict(e.attrib)) for e in owner.iter('node')
                if e is not owner and using == 'class name' and e.get('class') == value]


class FormApp:
    current_context = 'NATIVE_APP'
    current_package = PACKAGE
    current_activity = '.MainActivity'
    capabilities = {'platformVersion':'16'}
    switch_to = SimpleNamespace(context=lambda target: None)

    def __init__(self, submit='Begin shopping', accept_empty=False, bad_readback=False, text_options=False):
        self.submit, self.accept_empty, self.bad_readback = submit, accept_empty, bad_readback
        self.submissions, self.resets = [], 0
        self.text_options = text_options
        self.reset()

    def reset(self):
        self.name, self.country, self.gender = '', 'Alpha', 'Male'
        self.opened, self.error, self.view = False, '', 'entry'
        self.resets += 1

    @property
    def page_source(self):
        root = ElementTree.Element('hierarchy')
        frame = ElementTree.SubElement(root,'node',{'class':'android.widget.FrameLayout','package':PACKAGE,
                                                   'bounds':'[0,0][1080,2000]'})
        def node(cls, key='', text='', parent=frame, **extra):
            attributes = {'class':'android.widget.'+cls,'resource-id':key if ':' in key else PACKAGE+':id/'+key if key else '',
                          'text':text,'package':PACKAGE,'enabled':'true','displayed':'true',
                          'bounds':'[0,100][1080,800]',**extra}
            return ElementTree.SubElement(parent,'node',attributes)
        if self.opened:
            container = node('ListView','choices') if self.text_options else frame
            for value in ('Alpha','Beta','Gamma'):
                node('TextView' if self.text_options else 'CheckedTextView',
                     'android:id/text1' if self.text_options else '',text=value,parent=container,
                     clickable='true',checkable='true')
        elif self.view == 'products':
            node('TextView','heading','Products')
            node('TextView','product','Widget')
        else:
            node('TextView','heading','Entry')
            spinner = node('Spinner','country',clickable='true')
            node('TextView',text=self.country,parent=spinner)
            node('EditText','name',text=self.name,hint='Your Name',clickable='true')
            group = node('RadioGroup','gender')
            for gender in ('Male','Female'):
                node('RadioButton',gender.lower(),gender,parent=group,clickable='true',checkable='true',
                     checked=str(self.gender == gender).lower())
            node('Button','submit',self.submit,clickable='true')
            if self.error:
                node('TextView','error',self.error)
        return ElementTree.tostring(root,encoding='unicode')

    def find_elements(self, using, value):
        nodes = list(SafeTree.fromstring(self.page_source).iter('node'))
        if using == 'id':
            found = [e for e in nodes if e.get('resource-id') == value]
        elif using == '-android uiautomator':
            wanted = json.loads(re.search(r'\.text\((.*)\)',value).group(1))
            found = [e for e in nodes if e.get('text') == wanted]
        elif using == 'accessibility id':
            found = [e for e in nodes if e.get('content-desc') == value]
        else:
            found = []
        return [Element(self,dict(e.attrib)) for e in found]

    def is_keyboard_shown(self):
        return False

    def back(self):
        self.opened = False

    def observe(self):
        return normalize_screens([extract_screen(self.page_source,PACKAGE,'emulator-5554','.MainActivity')])[0]


def session(root, app=None, **settings):
    app = app or FormApp()
    launch = app.observe()
    config = {'app_mode':'installed','package_name':PACKAGE,'device_id':'emulator-5554',
              'interaction_testing':True,'test_all_discovered':True,**settings}
    def fresh():
        app.reset()
        return app.observe()
    device = SimpleNamespace(driver=app,config=config,screens=[launch],stop_path=root/'STOP',max_tries=100,
                             deadline=time.monotonic()+300,fresh_start=fresh,go_to=lambda screen:fresh(),
                             observe=app.observe)
    return AppSession(device), launch, app
