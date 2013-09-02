#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    Prestapyt is a library for Python to interact with the PrestaShop's Web Service API.
    Prestapyt is a direct port of the PrestaShop PHP API Client, PSWebServiceLibrary.php

    Credits:
    Thanks to Prestashop SA for their PHP API Client PSWebServiceLibrary.php
    Thanks to Alex Dean for his port of PSWebServiceLibrary.php to the Scala language (https://github.com/orderly/prestashop-scala-client)
    from which I also inspired my library.

    Questions, comments? guewen.baconnier@gmail.com
"""

__author__ = "Guewen Baconnier <guewen.baconnier@gmail.com>"
__version__ = "0.4.0"

import urllib
import warnings
import requests
import xml2dict
import dict2xml
import unicode_encode
import base64
from cStringIO import StringIO

from xml.parsers.expat import ExpatError
from xml.dom.minidom import parseString
from distutils.version import LooseVersion
try:
    from xml.etree import cElementTree as ElementTree
except ImportError, e:
    from xml.etree import ElementTree

requests.defaults.defaults['base_headers']['User-Agent'] = 'Prestapyt: Python Prestashop Library'


class PrestaShopWebServiceError(Exception):
    """Generic PrestaShop WebServices error class

    To catch these, you need to import it in you code e.g. :
    from prestapyt import PrestaShopWebServiceError
    """

    def __init__(self, msg, error_code=None, ps_error_msg='', ps_error_code=None):
        self.msg = msg
        self.error_code = error_code
        self.ps_error_msg = ps_error_msg
        self.ps_error_code = ps_error_code

    def __str__(self):
        return repr(self.ps_error_msg)


class PrestaShopAuthenticationError(PrestaShopWebServiceError):
    pass


class PrestaShopWebService(object):
    """
    Interacts with the PrestaShop WebService API, use XML for messages
    """

    MIN_COMPATIBLE_VERSION = '1.4.0.17'
    MAX_COMPATIBLE_VERSION = '1.5.4.0'

    def __init__(self, api_url, api_key, debug=False, headers=None, client_args=None):
        """
        Create an instance of PrestashopWebService.

        In your code, you can use :
        from prestapyt import PrestaShopWebService, PrestaShopWebServiceError

        try:
            prestashop = PrestaShopWebService.new('http://localhost:8080/api', 'BVWPFFYBT97WKM959D7AVVD0M4815Y1L')
        rescue PrestaShopWebServiceError, e:
            print str(e)
            ...

        @param api_url: Root URL for the shop
        @param api_key: Authentification key
        @param debug: Debug mode Activated (True) or deactivated (False)
        @param headers: Custom header, is a dict accepted by httplib2 as instance {'User-Agent': 'Schkounitz'}
        @param client_args: Dict of extra arguments for HTTP Client (httplib2) as instance {'timeout': 10.0}
        """
        if client_args is None: client_args = {}

        # required to hit prestashop
        self._api_url = api_url

        # add a trailing slash to the url if there is not one
        if not self._api_url.endswith('/'):
            self._api_url += '/'

        # add a trail /api/ if there is not
        if not self._api_url.endswith('/api/'):
            self._api_url += 'api/'

        # optional arguments
        self.debug = debug
        client_args.update({'auth' : (api_key, '')})

        # use header you coders you want, otherwise, use a default
        self.headers = {} if headers is None else headers

        # init http client in the init for re-use the same connection for all call
        self.client = requests.session(**client_args)

    def _parse_error(self, xml_content):
        """
        Take the XML content as string and extracts the PrestaShop error
        @param xml_content: xml content returned by the PS server as string
        @return (prestashop_error_code, prestashop_error_message)
        """
        error_answer = self._parse(xml_content)
        ps_error_code = ''
        ps_error_msg = ''
        if isinstance(error_answer, dict):
            error_content = error_answer.get('prestashop', {}).get('errors', {}).get('error', {})
        return (error_content.get('code'), error_content.get('message'))


    def _check_status_code(self, status_code, content):
        """
        Take the status code and throw an exception if the server didn't return 200 or 201 code
        @param status_code: status code returned by the server
        @return: True or raise an exception PrestaShopWebServiceError
        """
        message_by_code = {204: 'No content',
                           400: 'Bad Request',
                           401: 'Unauthorized',
                           404: 'Not Found',
                           405: 'Method Not Allowed',
                           500: 'Internal Server Error',}

        if status_code in (200, 201):
            return True
        elif status_code == 401:
            # the content is empty for auth errors
            raise PrestaShopAuthenticationError(message_by_code[status_code],
                status_code)
        elif status_code in message_by_code:
            ps_error_code, ps_error_msg = self._parse_error(content)
            raise PrestaShopWebServiceError(message_by_code[status_code],
                status_code, ps_error_msg, ps_error_code)
        else:
            ps_error_code, ps_error_msg = self._parse_error(content)
            raise PrestaShopWebServiceError('Unknown error', status_code,
                ps_error_msg, ps_error_code)

    def _check_version(self, version):
        """
        Check if this library is compatible with the called PrestaShop WebService

        @param version: version returned by the PrestaShop webservice
        @return: True if the library is compatible. Otherwise raise an error PrestaShopWebServiceError
        """
        if version:
            if not (LooseVersion(self.MIN_COMPATIBLE_VERSION) <
                    LooseVersion(version) <=
                    LooseVersion(self.MAX_COMPATIBLE_VERSION)):
                warnings.warn(("This library may not be compatible with this version of PrestaShop (%s). "
                     "Please upgrade/downgrade this library") % (version,))
        return True

    def _execute(self, url, method, data=None, files=None, add_headers=None):
        """
        Execute a request on the PrestaShop Webservice

        @param url: full url to call
        @param method: GET, POST, PUT, DELETE, HEAD
        @param data: for PUT (edit) and POST (add) only, the xml sent to PrestaShop
        @param files: should contain {'image': (img_filename, img_file)}
        @param add_headers: additional headers merged on the instance's headers
        @return: tuple with (status code, header, content) of the response
        """
        if add_headers is None: add_headers = {}

        # Don't print when method = POST, because it contains an encoded URL
        # The print for POST is in the method add_with_url()
        if self.debug and data and method <> 'POST':
            try:
                xml = parseString(data)
                pretty_body = xml.toprettyxml(indent="  ")
            except:
                pretty_body = data
            print "Execute url: %s / method: %s\nbody: %s" % (url, method, pretty_body)

        request_headers = self.headers.copy()
        request_headers.update(add_headers)

        if not files:
            r = self.client.request(method, url, data=data, headers=request_headers)
        else:
            r = self.client.request(method, url, files=files)

        if self.debug: # TODO better debug logs
            print ("Response code: %s\nResponse headers:\n%s\n"
                   % (r.status_code, r.headers))
            if r.headers.get('content-type') and r.headers.get('content-type').startswith('image'):
                print "Response body: Image in binary format\n"
            else:
                print "Response body:\n%s\n" % r.content

        self._check_status_code(r.status_code, r.content)
        self._check_version(r.headers.get('psws-version'))

        return r

    def _parse(self, content):
        """
        Parse the response of the webservice

        @param content: response from the webservice
        @return: an ElementTree of the content
        """
        if not content:
            raise PrestaShopWebServiceError('HTTP response is empty')

        try:
            # We have to encode it in utf-8, because content has the XML header
            # cf http://lxml.de/FAQ.html#why-can-t-lxml-parse-my-xml-from-unicode-strings
            # WARNING : old versions of 'requests', for instance version 0.8.2
            # packaged in Ubuntu 12.04, return a unicode... but more recent of
            # requests, for instance 0.13.5 return a str in utf-8 !
            parsed_content = ElementTree.fromstring(unicode_encode.unicode2encoding(content))
        except ExpatError, err:
            raise PrestaShopWebServiceError('HTTP XML response is not parsable : %s' % (err,))

        return parsed_content

    def _validate(self, options):
        """
        Check options against supported options
        (reference : http://doc.prestashop.com/display/PS14/Cheat+Sheet_+Concepts+Outlined+in+this+Tutorial)

        This syntax also works for options dict :
        (reference : http://www.prestashop.com/forums/topic/101502-webservice-api-filter-for-date-ranges/#post_id_708102)
                {'filter[date_upd]': '>[2012-07-30]',
                'date': '1'}
            will returns :
                '/?filter[date_upd]=>[2012-07-30]&date=1'
            you may also define {'filter[date_upd]': '>[2012-07-30 16:00:00]', 'date': '1'}
            Note : you must consider that '>[2012-07-30]' is interpreted like 'equal or greater than' by web service

        @param options: dict of options to use for the request
        @return: True if valid, else raise an error PrestaShopWebServiceError
        """
        if not isinstance(options, dict):
            raise PrestaShopWebServiceError('Parameters must be a instance of dict')
        supported = ('filter', 'display', 'sort', 'limit', 'schema', 'date', 'date_filter', 'id_shop')
        # filter[firstname] (as e.g.) is allowed, so check only the part before a [
        unsupported = set([param.split('[')[0] for param in options]).difference(supported)
        if unsupported:
            raise PrestaShopWebServiceError('Unsupported parameters: %s'
            % (', '.join(tuple(unsupported)),))
        return True

    def _options_to_querystring(self, options):
        """
        Translate the dict of options to a url form
        As instance :
        {'display': '[firstname,lastname]',
         'filter[id]': '[1|5]'}
        will returns :
        'display=[firstname,lastname]&filter[id]=[1|5]'

        @param options: dict of options for the request
        @return: string to use in the url
        """
        if self.debug:
            options.update({'debug': True})
        if options.get('date_filter'):
            options['date'] = 1
            for field, operator, date in options.pop('date_filter'):
                options['filter[%s]'%field] = '%s[%s]'%(operator, date.strftime('%Y-%m-%d %H:%M:%S'))
        return urllib.urlencode(options)

    def add(self, resource, content, img_filename=None):
        """
        Add (POST) a resource. The content can be a dict of values to create.

        @param resource: type of resource to create
        @param content: Full XML as string or dict of new resource values.
            If a dict is given, it will be converted to XML with the necessary
            root tag ie:
            <prestashop>[[dict converted to xml]]</prestashop>
            If we add an image, it should contain the binary of the image as string.
        @param img_filename: Filename of the image with its extension as string,
            for example 'myproduct.jpg'
        @return: an ElementTree of the response from the web service if it's an XML
            or True if the response from the web service is a binary
        """
        if img_filename:
            # Check that we have a valid filename with an extension
            if isinstance(img_filename, (str, unicode)) and 1<=len(img_filename)<= 255 and "/" not in img_filename and "\000" not in img_filename and '.' in img_filename:
                if self.debug:
                    print "Filename '%s' considered valid" % img_filename
            else:
                raise PrestaShopWebServiceError('Invalid image filename: %s'
                            % img_filename)

        return self.add_with_url(self._api_url + resource, content, img_filename=img_filename)

    def add_with_url(self, url, content, img_filename=None):
        """
        Add (POST) a resource

        @param url: A full URL which for the resource type to create
        @param content: a string containing the full XML of new resource or an image encoded in base64.
        @param img_filename: a string containing the filename of the image.
        @return: an ElementTree of the response from the web service
        """
        if not img_filename:
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            if self.debug and content:
                try:
                    xml = parseString(content)
                    pretty_body = xml.toprettyxml(indent="  ")
                except:
                    pretty_body = content
                print "Execute url: %s / method: POST\nbody: %s" % (url, pretty_body)

            r = self._execute(url, 'POST', data=urllib.urlencode({'xml': content.encode('utf-8')}), add_headers=headers)
        else:
            img_binary = base64.decodestring(content)
            img_file = StringIO(img_binary)
            r = self._execute(url, 'POST', files={'image': (img_filename, img_file)})
        if r.headers.get('content-type') and r.headers.get('content-type').startswith('image'):
            return True
        else:
            return self._parse(r.content)

    def search(self, resource, options=None):
        """
        Retrieve (GET) a resource and returns the xml with the ids.
        Is not supposed to be called with an id or whatever in the resource line 'addresses/1'
        But only with 'addresses' or 'products' etc...
        This method is only a mapper to the get method without the resource_id, but semantically
        it is more clear than "get without id" to search resources

        @param resource: string of the resource to search like 'addresses', 'products'
        @param options:  Optional dict of parameters to filter the search (one or more of
                            'filter', 'display', 'sort', 'limit', 'schema')
        @return: ElementTree of the xml message
        """
        return self.get(resource, options=options)

    def get(self, resource, resource_id=None, options=None):
        """
        Retrieve (GET) a resource

        @param resource: type of resource to retrieve
        @param resource_id: optional resource id to retrieve
        @param options: Optional dict of parameters (one or more of
                        'filter', 'display', 'sort', 'limit', 'schema')
        @return: an ElementTree of the response
        """
        full_url = self._api_url + resource
        if resource_id is not None:
            full_url += "/%s" % (resource_id,)
        if options is not None:
            self._validate(options)
            full_url += "?%s" % (self._options_to_querystring(options),)
        return self.get_with_url(full_url)

    def get_with_url(self, url):
        """
        Retrieve (GET) a resource from a full URL

        @param url: An URL which explicitly sets the resource type and ID to retrieve
        @return: an ElementTree of the resource
        """
        r = self._execute(url, 'GET')
        if r.headers.get('content-type') and r.headers.get('content-type').startswith('image'):
            return r.content
        else:
            return self._parse(r.content)

    def head(self, resource, resource_id=None, options=None):
        """
        Head method (HEAD) a resource

        @param resource: type of resource to retrieve
        @param resource_id: optional resource id to retrieve
        @param options: Optional dict of parameters (one or more of 'filter', 'display', 'sort', 'limit', 'schema')
        @return: the header of the response as a dict
        """
        full_url = self._api_url + resource
        if resource_id is not None:
            full_url += "/%s" % (resource_id,)
        if options is not None:
            self._validate(options)
            full_url += "?%s" % (self._options_to_querystring(options),)
        return self.head_with_url(full_url)

    def head_with_url(self, url):
        """
        Head method (HEAD) a resource from a full URL

        @param url: An URL which explicitly sets the resource type and ID to retrieve
        @return: the header of the response as a dict
        """
        return self._execute(url, 'HEAD').headers

    def edit(self, resource, content):
        """
        Edit (PUT) a resource.

        @param resource: type of resource to edit
        @param resource_id: id of the resource to edit
        @param content: modified XML as string of the resource.
        @return: an ElementTree of the Webservice's response
        """
        full_url = "%s%s" % (self._api_url, resource)
        return self.edit_with_url(full_url, content)

    def edit_with_url(self, url, content):
        """
        Edit (PUT) a resource from a full URL

        @param url: an full url to edit a resource
        @param content: modified XML as string of the resource.
        @return: an ElementTree of the Webservice's response
        """
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        r = self._execute(unicode_encode.encode(url), 'PUT', data=unicode_encode.encode(content), add_headers=headers)
        return self._parse(r.content)

    def delete(self, resource, resource_ids):
        """
        Delete (DELETE) a resource.

        @param resource: type of resource to retrieve
        @param resource_ids: int or list of ids to delete
        @return: True if delete is done, raise an error PrestaShopWebServiceError if missed
        """
        full_url = self._api_url + resource
        if isinstance(resource_ids, (tuple, list)):
            full_url += "/?id=[%s]" % \
                        (','.join([str(resource_id) for resource_id in resource_ids]),)
        else:
            full_url += "/%s" % str(resource_ids)
        return self.delete_with_url(full_url)

    def delete_with_url(self, url):
        """
        Delete (DELETE) a resource.

        @param url: full URL to delete a resource
        @return: True if delete is done, raise an error PrestaShopWebServiceError if missed
        """
        self._execute(url, 'DELETE')
        return True


class PrestaShopWebServiceDict(PrestaShopWebService):
    """
    Interacts with the PrestaShop WebService API, use dict for messages
    """

    def search(self, resource, options=None):
        """
        Retrieve (GET) a resource and returns a list of its ids.
        Is not supposed to be called with an id or whatever in the resource line 'addresses/1'
        But only with 'addresses' or 'products' etc...

        @param resource: string of the resource to search like 'addresses', 'products'
        @param options:  Optional dict of parameters to filter the search (one or more of 'filter', 'display', 'sort', 'limit', 'schema')
        @return: list of ids as int
        """
        def dive(response, level=1):
            # not deterministic but we know that we only have one key
            # in the response for the first 2 levels like
            # {'addresses': {'address': ...} this method has just
            # purpose to dive of n level in the response
            if not response:
                return False
            if level > 0:
                return dive(response[response.keys()[0]], level=level-1)
            return response

        # returned response looks like :
        # for many resources :
        # {'addresses': {'address': [{'attrs': {'id': '1'}, 'value': ''},
        #                            {'attrs': {'id': '2'}, 'value': ''},
        #                            {'attrs': {'id': '3'}, 'value': ''}]}}
        # for one resource :
        # {'addresses': {'address': {'attrs': {'id': '1'}, 'value': ''}}}
        # for zero resource :
        # {'addresses': ''}
        response = super(PrestaShopWebServiceDict, self).\
                    search(resource, options=options)

        elems = dive(response, level=2)
        # when there is only 1 resource, we do not have a list in the response
        if not elems:
            return []
        elif isinstance(elems, list):
            ids = [int(elem['attrs']['id']) for elem in elems]
        else:
            ids = [int(elems['attrs']['id'])]
        return ids

    def get(self, resource, resource_id=None, options=None):
        """
        Retrieve (GET) a resource

        @param resource: type of resource to retrieve
        @param resource_id: optional resource id to retrieve
        @param options: Optional dict of parameters (one or more of
                        'filter', 'display', 'sort', 'limit', 'schema')
        @return: a dict of the response
        """
        response = super(PrestaShopWebServiceDict, self).get(resource, resource_id=resource_id, options=options)
        if resource == 'images/products' and resource_id:
            images = []
            for image in response['image']['declination']:
                image_id = image['attrs']['id']
                image_url = '%s%s/%s/%s'%(self._api_url, resource, resource_id, image_id)
                images.append({
                    'id': image_id,
                    'image': self._execute(image_url, 'get').content
                })
            return images
        return response

    def get_with_url(self, url):
        """
        Retrieve (GET) a resource from a full URL

        @param url: An URL which explicitly sets the resource type and ID to retrieve
        @return: a dict of the response. Remove root keys ['prestashop'] from the message
        """
        response = super(PrestaShopWebServiceDict, self).get_with_url(url)
        if isinstance(response, dict):
            return response['prestashop']
        else:
            return response

    def partial_add(self, resource, fields):
        """
        Add (POST) a resource without necessary all the content.
        Retrieve the full empty envelope
        and merge the given fields in this envelope.

        @param resource: type of resource to create
        @param fields: dict of fields of the resource to create
        @return: response of the server
        """
        blank_envelope = self.get(resource, options={'schema': 'blank'})
        complete_content = dict(blank_envelope, **fields)
        return self.add(resource, complete_content)

    def partial_edit(self, resource, resource_id, fields):
        """
        Edit (PUT) partially a resource.
        Standard REST PUT means a full replacement of the resource.
        Allows to edit only only some fields of the resource with
        a perf penalty. It will read on prestashop,
        then modify the keys in content,
        and write on prestashop.

        @param resource: type of resource to edit
        @param resource_id: id of the resource to edit
        @param fields: dict containing the field name as key
            and the values of the files to modify
        @return: an ElementTree of the Webservice's response
        """
        complete_content = self.get(resource, resource_id)
        for key in complete_content:
            if fields.get(key):
                complete_content[key].update(fields[key])
        return self.edit(resource, complete_content)

    def add_with_url(self, url, content, img_filename=None):
        """
        Add (POST) a resource

        @param url: A full URL which for the resource type to create
        @param content: a string containing the full XML of new resource
           or an image encoded in base64.
        @param img_filename: a string containing the filename of the image.
        @return: a dict of the response from the web service or True if the
           response is a binary.
        """
        if isinstance(content, dict):
            xml_content = dict2xml.dict2xml({'prestashop': content})
        else:
            xml_content = content
        res = super(PrestaShopWebServiceDict, self).add_with_url(url, xml_content, img_filename=img_filename)
        if isinstance(res, dict) and res.get('prestashop'):
            res_l2 = res['prestashop'].keys()
            if 'content' in res['prestashop'].keys():
                res_l2.remove('content')
            return res['prestashop'][res_l2[0]]['id']
        else:
            return True

    def edit_with_url(self, url, content):
        """
        Edit (PUT) a resource from a full URL

        @param url: an full url to edit a resource
        @param content: modified dict of the resource.
        @return: an ElementTree of the Webservice's response
        """
        xml_content = dict2xml.dict2xml({'prestashop': content})
        return super(PrestaShopWebServiceDict, self).edit_with_url(url, xml_content)

    def _parse(self, content):
        """
        Parse the response of the webservice, assumed to be a XML in utf-8

        @param content: response from the webservice
        @return: a dict of the content
        """
        parsed_content = super(PrestaShopWebServiceDict, self)._parse(content)
        return xml2dict.ET2dict(parsed_content)


if __name__ == '__main__':
    prestashop = PrestaShopWebServiceDict('http://localhost:8080/api',
                                          'BVWPFFYBT97WKM959D7AVVD0M4815Y1L')
    #prestashop.debug = True

    from pprint import pprint

    pprint(prestashop.get(''))
    pprint(prestashop.head(''))

    pprint(prestashop.search('addresses'))
    pprint(prestashop.search('addresses', options={'limit': 0}))
    pprint(prestashop.search('addresses', options={'limit': 1}))
    pprint(prestashop.search('products'))
    pprint(prestashop.search('customers'))
    pprint(prestashop.search('carts'))
    pprint(prestashop.search('categories'))
    pprint(prestashop.search('configurations'))
    pprint(prestashop.search('languages'))

    pprint(prestashop.get('addresses', 1))
    pprint(prestashop.get('addresses', 1))
    pprint(prestashop.get('products', 1))

    address_data = prestashop.get('addresses', 1)
    address_data['address']['firstname'] = 'Robert'
    prestashop.edit('addresses', 1, address_data)

    address_data = prestashop.get('addresses', options={'schema': 'blank'})
    address_data['address'].update({'address1': '1 Infinite Loop',
                                    'address2': '',
                                    'alias': 'manufacturer',
                                    'city': 'Cupertino',
                                    'company': '',
                                    'deleted': '0',
                                    'dni': '',
                                    'firstname': 'STEVE',
                                    'id_country': '21',
                                    'id_customer': '',
                                    'id_manufacturer': '1',
                                    'id_state': '5',
                                    'id_supplier': '',
                                    'lastname': 'JOBY',
                                    'other': '',
                                    'phone': '(800) 275-2273',
                                    'phone_mobile': '',
                                    'postcode': '95014',
                                    'vat_number': ''})
    prestashop.add('addresses', address_data)
