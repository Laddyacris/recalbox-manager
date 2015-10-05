"""
Views for roms
"""
import json, os
from operator import itemgetter

from django.conf import settings
from django.views.generic import TemplateView
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.utils.translation import ugettext as _

from project.manager_frontend.forms.roms import RomUploadForm, RomDeleteForm
from project.utils.views import MultiFormView


class SystemsListView(TemplateView):
    """
    List rom system folders
    """
    template_name = "manager_frontend/systems_list.html"
            
    def get_system_list(self):
        path = settings.RECALBOX_ROMS_PATH
        system_dirs = []
        for item in os.listdir(path):
            # Only display directories
            if os.path.isdir(os.path.join(path, item)) and not item.startswith('.'):
                # Try to find the dirname in the system manifest
                if item in settings.RECALBOX_MANIFEST:
                    system_dirs.append( (item, settings.RECALBOX_MANIFEST[item]['name']) )
                # Unknowed dirname
                else:
                    system_dirs.append( (item, item) )
        
        return sorted(system_dirs, key=itemgetter(0))
            
    def get_context_data(self, **kwargs):
        context = super(SystemsListView, self).get_context_data(**kwargs)
        context.update({
            'systems_path': settings.RECALBOX_ROMS_PATH,
            'systems_list': self.get_system_list(),
        })
        return context



class RomListView(MultiFormView):
    """
    List rom from a system folder with an upload form and delete form
    
    This is a huge rewrite and mixing of some CBV views and mixins to be able 
    to distinctly manage the two forms
    
    Upload form part is only used with browser that dont accept Javascript, others 
    use the Dropzone plugin and so are routed to 'RomUploadJsonView'.
    """
    template_name = "manager_frontend/rom_list.html"
    enabled_forms = (RomUploadForm, RomDeleteForm)
            
    def init_system(self):
        self.system_key = self.kwargs.get('system')
        self.system_path = os.path.join(settings.RECALBOX_ROMS_PATH, self.system_key)
        
        # Only display existing and not hidded directories
        if not os.path.exists(self.system_path) or not os.path.isdir(self.system_path) or self.system_key.startswith('.'):
            raise Http404
        
        default_manifest = settings.RECALBOX_SYSTEM_DEFAULT
        default_manifest.update({
            'key': self.system_key,
            'name': self.system_key
        })
        # Get the system manifest part if any, else a default dict
        self.system_manifest = settings.RECALBOX_MANIFEST.get(self.system_key, default_manifest)
            
    def get_rom_choices(self):
        rom_list = []
        
        for item in os.listdir(self.system_path):
            if os.path.isfile(os.path.join(self.system_path, item)) and not item.startswith('.'):
                rom_list.append( (item, os.path.getsize(os.path.join(self.system_path, item))) )
        
        return tuple( sorted(rom_list, key=itemgetter(0)) )
            
    def get_context_data(self, **kwargs):
        context = super(RomListView, self).get_context_data(**kwargs)
        context.update({
            'system': self.system_key,
            'system_path': self.system_path,
            'system_name': self.system_manifest['name'],
            'system_manifest': self.system_manifest,
            'total_roms': len(self.get_rom_choices()),
        })
        return context

    def get_success_url(self):
        return reverse('manager:roms-list', args=[self.kwargs.get('system')])
    
    def get_upload_form_kwargs(self, kwargs):
        kwargs.update({
            'system_manifest': self.system_manifest,
            'system': self.system_key,
        })
        return kwargs
    
    def get_delete_form_kwargs(self, kwargs):
        kwargs.update({
            'romchoices': self.get_rom_choices(),
            'system': self.system_key,
        })
        return kwargs
        
    def upload_form_valid(self, form):
        uploaded_file = form.save()
        
        # Throw a message to tell about upload success
        messages.success(self.request, _('File has been uploaded: {}').format(os.path.basename(uploaded_file)))
            
    def delete_form_valid(self, form):
        deleted_files = form.save()
        if deleted_files and len(deleted_files)>0:
            deleted_files = ", ".join([os.path.basename(item) for item in deleted_files])
            # Throw a message to tell about deleted files
            messages.success(self.request, _('Deleted file(s): {}').format( deleted_files ))
        
    def get(self, request, *args, **kwargs):
        self.init_system()
        return super(RomListView, self).get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        self.init_system()
        return super(RomListView, self).post(request, *args, **kwargs)



class RomUploadJsonView(RomListView):
    """
    Inherit from RomListView to be similary but gives only response in JSON
    
    Also the delete form should not really be used here
    """
    def upload_form_valid(self, form):
        """
        Return a dummy success response suitable to Dropzone plugin
        """
        uploaded_file = form.save()
        
        return self.json_response({'status': 'success'})

    def form_invalid(self, *args):
        """
        Tricky error JSON response for upload
        
        This is a naive implementation than assume this is only about rom upload 
        form errors.
        """
        forms_errors = {'error': 'Unknow error occured'}
        error_msg = ''
        
        for form in args:
            # Bother only about upload form
            if form.form_key == 'upload':
                errs = form.errors.as_data()
                # Get error(s), potentially compact them if more than one message
                if 'rom' in errs:
                    error_context = [str(item.message) for item in errs['rom']]
                    if len(error_context) > 1:
                        error_msg = "\n".join(error_context)
                    elif len(error_context) == 1:
                        error_msg = "".join(error_context)
            else:
                continue
        
        if error_msg:
            forms_errors['error'] = error_msg
        
        return self.json_response(forms_errors, response_klass=HttpResponseBadRequest)
    
    def json_response(self, backend, response_klass=HttpResponse):
        """
        Attemp a JSON string as the backend
        
        If not a string, assume this is an object suitable to JSON and convert it with json.dumps(...)
        
        Return a HttpResponse with right content_type and some cache 
        headers (to avoid response caching)
        """
        if not isinstance(backend, basestring):
            backend = json.dumps(backend)
        
        content_type = "application/json; charset=utf-8"
        
        response = response_klass(backend, content_type=content_type)
        
        response['Pragma'] = "no-cache"
        response['Cache-Control'] = "no-cache, no-store, must-revalidate, max-age=0" 
        
        return response
