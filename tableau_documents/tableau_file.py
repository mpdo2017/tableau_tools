# -*- coding: utf-8 -*-

import zipfile
import os
import shutil
import codecs
from typing import Union, Any, Optional, List, Dict, Tuple
import xml.etree.ElementTree as ET
import io
from abc import ABC, abstractmethod

from tableau_tools.logging_methods import LoggingMethods
from tableau_tools.logger import Logger
from tableau_tools.tableau_exceptions import *
from .tableau_datasource import TableauDatasource
from .tableau_workbook import TableauWorkbook
# from tableau_documents.tableau_document import TableauDocument


class TableauFile(LoggingMethods):
    def __init__(self, filename: str, logger_obj: Optional[Logger] = None,
                 create_new: bool = False, ds_version: Optional[str] = '10'):
        self.logger: Optional[Logger] = logger_obj
        self.log('TableauFile initializing for {}'.format(filename))
        self.packaged_file: bool = False
        self.packaged_filename: Optional[str] = None
        self.tableau_xml_file: Optional[ET.Element] = None
        #self._tableau_document: Optional[TableauDocument] = None
        self._original_file_type: Optional[str] = None
        self._final_file_type: Optional[str] = None
        self.other_files: List[str] = []
        self.temp_filename: Optional[str] = None
        self.orig_filename: str = filename
        self._document_type = None

        if filename is None:
            # Assume we start as TDS when building from scratch
            self._original_file_type = 'tds'
            self._final_file_type = 'tds'
        if filename.lower().find('.tdsx') != -1:
            self._original_file_type = 'tdsx'
            self._final_file_type = 'tdsx'
            self.packaged_file = True
        elif filename.lower().find('.twbx') != -1:
            self._original_file_type = 'twbx'
            self._final_file_type = 'twbx'
            self.packaged_file = True
        elif filename.lower().find('.twb') != -1:
            self._original_file_type = 'twb'
            self._final_file_type = 'twb'
        elif filename.lower().find('.tds') != -1:
            self._original_file_type = 'tds'
            self._final_file_type = 'tds'
        elif filename.lower().find('tfl') != -1:
            self._original_file_type = 'tfl'
            self._final_file_type = 'tfl'
        else:
            raise InvalidOptionException('Must open a Tableau file with ending of tds, tdsx, twb, twbx, tfl')
        try:
            if create_new is True:
                if self._original_file_type in ['tds', 'tdsx']:
                    self._tableau_document = TableauDatasource(None, logger_obj, ds_version=ds_version)
                else:
                    raise InvalidOptionException('Cannot create a new TWB or TWBX from scratch currently')
            else:
                file_obj = open(filename, 'rb')
                self.log('File type is {}'.format(self.file_type))
                # Extract the TWB or TDS file to disk, then create a sub TableauFile
                if self.file_type in ['twbx', 'tdsx']:
                    self.zf = zipfile.ZipFile(file_obj)
                    # Ignore anything in the subdirectories
                    for name in self.zf.namelist():
                        if name.find('/') == -1:
                            if name.endswith('.tds'):
                                self.log('Detected a TDS file in archive, saving temporary file')
                                self.packaged_filename = os.path.basename(self.zf.extract(name))
                            elif name.endswith('.twb'):
                                self.log('Detected a TWB file in archive, saving temporary file')
                                self.packaged_filename = os.path.basename(self.zf.extract(name))
                        else:
                            self.other_files.append(name)

                    self.tableau_xml_file = TableauFile(self.packaged_filename, self.logger)
                    self._tableau_document = self.tableau_xml_file._tableau_document
                elif self.file_type == 'twb':
                    self._tableau_document = TableauWorkbook(filename, self.logger)
                elif self.file_type == 'tds':
                    # Here we throw out metadata-records even when opening a workbook from disk, they take up space
                    # and are recreate automatically. Very similar to what we do in initialization of TableauWorkbook
                    o_ds_fh = codecs.open(filename, 'r', encoding='utf-8')
                    ds_fh = codecs.open('temp_file.txt', 'w', encoding='utf-8')
                    self.temp_filename = 'temp_file.txt'
                    metadata_flag = None
                    for line in o_ds_fh:
                        # Grab the datasources

                        if line.find("<metadata-records") != -1 and metadata_flag is None:
                            metadata_flag = True
                        if metadata_flag is not True:
                            ds_fh.write(line)
                        if line.find("</metadata-records") != -1 and metadata_flag is True:
                            metadata_flag = False
                    o_ds_fh.close()

                    ds_fh.close()
                    utf8_parser = ET.XMLParser(encoding='utf-8')

                    ds_xml = ET.parse('temp_file.txt', parser=utf8_parser)

                    self._tableau_document = TableauDatasource(ds_xml.getroot(), self.logger)
                self.xml_name = None
                file_obj.close()
        except IOError:
            self.log("Cannot open file {}".format(filename))
            raise

    @property
    def tableau_document(self) -> Union[TableauDatasource, TableauWorkbook]:
        return self._tableau_document

    @property
    def file_type(self) -> str:
        return self._original_file_type

    @property
    def datasources(self) -> List[TableauDatasource]:
        if self._tableau_document.document_type == 'workbook':
            return self._tableau_document.datasources
        elif self._tableau_document.document_type == 'datasource':
            return [self._tableau_document, ]
        else:
            return []

    # Appropriate extension added if needed
    def save_new_file(self, new_filename_no_extension: str, data_file_replacement_map: Optional[Dict],
                      new_data_files_map: Optional[Dict]) -> str:
        self.start_log_block()
        new_filename = new_filename_no_extension.split('.')[0]  # simple algorithm to kill extension
        if new_filename is None:
            new_filename = new_filename_no_extension
        self.log('Saving to a file with new filename {}'.format(new_filename))
        # Change filetype if there are new extracts to add
        for ds in self.datasources:
            if ds.tde_filename is not None or new_data_files_map is not None:
                if self.file_type == 'twb':
                    self._final_file_type = 'twbx'
                    self.packaged_filename = "{}.twb".format(new_filename)
                    self.log('Final filetype will be TWBX')
                    break
                if self.file_type == 'tds' or new_data_files_map is not None:
                    self._final_file_type = 'tdsx'
                    self.packaged_filename = "{}.tds".format(new_filename)
                    self.log('Final filetype will be TDSX')
                    break

        if self._final_file_type in ['twbx', 'tdsx']:
            initial_save_filename = "{}.{}".format(new_filename, self._final_file_type)
            # Make sure you don't overwrite the existing original file
            files = list(filter(os.path.isfile, os.listdir(os.curdir)))  # files only
            save_filename = initial_save_filename
            file_versions = 1
            while save_filename in files:
                name_parts = initial_save_filename.split(".")
                save_filename = "{} ({}).{}".format(name_parts[0],file_versions, name_parts[1])
                file_versions += 1
            new_zf = zipfile.ZipFile(save_filename, 'w', zipfile.ZIP_DEFLATED)
            # Save the object down
            self.log('Creating temporary XML file {}'.format(self.packaged_filename))
            # Have to extract the original TWB to temporary file
            self.log('Creating from original file {}'.format(self.orig_filename))
            if self._original_file_type == 'twbx':
                file_obj = open(self.orig_filename, 'rb')
                o_zf = zipfile.ZipFile(file_obj)
                o_zf.extract(self.tableau_document.twb_filename)
                shutil.copy(self.tableau_document.twb_filename, 'temp.twb')
                os.remove(self.tableau_document.twb_filename)
                self.tableau_document.twb_filename = 'temp.twb'
                file_obj.close()

            # Call to the tableau_document object to write the Tableau XML
            self.tableau_document.save_file(self.packaged_filename)
            new_zf.write(self.packaged_filename)
            self.log('Removing file {}'.format(self.packaged_filename))
            os.remove(self.packaged_filename)

            if self._original_file_type == 'twbx':
                os.remove('temp.twb')
                self.log('Removed file temp.twb'.format(self.packaged_filename))

            temp_directories_to_remove = {}

            if len(self.other_files) > 0:
                file_obj = open(self.orig_filename, 'rb')
                o_zf = zipfile.ZipFile(file_obj)

                # Find datasources with new extracts, and skip their files
                extracts_to_skip = []
                for ds in self.tableau_document.datasources:
                    if ds.existing_tde_filename is not None and ds.tde_filename is not None:
                        extracts_to_skip.append(ds.existing_tde_filename)

                for filename in self.other_files:
                    self.log('Looking into additional files: {}'.format(filename))

                    # Skip extracts listed for replacement
                    if filename in extracts_to_skip:
                        self.log('File {} is from an extract that has been replaced, skipping'.format(filename))
                        continue

                    # If file is listed in the data_file_replacement_map, write data from the mapped in file
                    if data_file_replacement_map and filename in data_file_replacement_map:
                        new_zf.write(data_file_replacement_map[filename], "/" + filename)
                        # Delete from the data_file_replacement_map to reduce down to end
                        del data_file_replacement_map[filename]
                    else:
                        o_zf.extract(filename)
                        new_zf.write(filename)
                        os.remove(filename)
                    self.log('Removed file {}'.format(filename))
                    lowest_level = filename.split('/')
                    temp_directories_to_remove[lowest_level[0]] = True
                file_obj.close()

            # Loop through remaining files in data_file_replacement_map to just add
            for filename in new_data_files_map:
                new_zf.write(new_data_files_map[filename], "/" + filename)

            # If new extract, write that file
            for ds in self.tableau_document.datasources:
                if ds.tde_filename is not None:
                    new_zf.write(ds.tde_filename, '/Data/Datasources/{}'.format(ds.tde_filename))
                    os.remove(ds.tde_filename)
                    self.log('Removed file {}'.format(ds.tde_filename))

            # Cleanup all the temporary directories
            for directory in temp_directories_to_remove:
                self.log('Removing directory {}'.format(directory))
                try:
                    shutil.rmtree(directory)
                except OSError as e:
                    # Just means that directory didn't exist for some reason, probably a swap occurred
                    pass
            new_zf.close()

            return save_filename
        else:
            initial_save_filename = "{}.{}".format(new_filename_no_extension, self.file_type)
            # Make sure you don't overwrite the existing original file
            files = list(filter(os.path.isfile, os.listdir(os.curdir)))  # files only
            save_filename = initial_save_filename
            file_versions = 1
            while save_filename in files:
                name_parts = initial_save_filename.split(".")
                save_filename = "{} ({}).{}".format(name_parts[0],file_versions, name_parts[1])
                file_versions += 1

            self.tableau_document.save_file(save_filename)
            return save_filename


# Hyper files are not considered in this situation as they are binary and generated a different way

# This is a helper class with factory and static methods
class TableauFileManager(LoggingMethods):

    @staticmethod
    def open(filename: str, logger_obj: Optional[Logger] = None):
        # logger_obj.log('Opening {}'.format(filename))
        # Packaged (X) files must come first because they are supersets
        if filename.lower().find('.tdsx') != -1:

            return TDSX(filename=filename, logger_obj=logger_obj)
        elif filename.lower().find('.twbx') != -1:

            return TWBX(filename=filename, logger_obj=logger_obj)
        elif filename.lower().find('.tflx') != -1:

            return TFLX(filename=filename, logger_obj=logger_obj)
        elif filename.lower().find('.twb') != -1:

            return TWB(filename=filename, logger_obj=logger_obj)
        elif filename.lower().find('.tds') != -1:

            return TDS(filename=filename, logger_obj=logger_obj)
        elif filename.lower().find('tfl') != -1:

            return TFL(filename=filename, logger_obj=logger_obj)
        else:
            raise InvalidOptionException('Must open a Tableau file with ending of tds, tdsx, twb, twbx, tfl, tflx')



    # For saving a TWB or TDS (or other) from a document object. Actually should be
    @staticmethod
    def create_new_tds(tableau_datasource: TableauDatasource):
        pass

    @staticmethod
    def create_new_tdsx(tableau_datasource: TableauDatasource):
        pass

    @staticmethod
    def create_new_twb(tableau_workbook: TableauWorkbook):
        pass

    @staticmethod
    def create_new_twbx(tableau_workbook: TableauWorkbook):
        pass

class DatasourceMethods(ABC):
    @property
    @abstractmethod
    def datasources(self) -> List[TableauDatasource]:
        #return self._datasources
        pass

# One of the principles of tableau_documents design is: Use the original XML as generated by Tableau Desktop
# as much as possible. Another principle: Wait to write anything until the save functions are called, so that in-memory changes
# are always included in their final state.
# In this model, the objects that end in File are responsible for reading and writing from disk, while the
# "tableau_document" objects handle any changes to XML.
# The saving chain is thus that a PackagedFile calls to a TableauFile to get the file it is writing
# and the TableauFile writes to disk by calling the TableauDocument to export its XML as a string

# Abstract implementation
class TableauXmlFile(LoggingMethods, ABC):
    def __init__(self, filename: str, logger_obj: Optional[Logger] = None):
        self.logger: Optional[Logger] = logger_obj
        self.tableau_document = None
        self.packaged_file: bool = False

    @property
    @abstractmethod
    def file_type(self) -> str:
        pass


    # Appropriate extension added if needed
    def save_new_file(self, new_filename_no_extension: str) -> str:
        self.start_log_block()
        new_filename = new_filename_no_extension.split('.')[0]  # simple algorithm to kill extension
        if new_filename is None:
            new_filename = new_filename_no_extension
        self.log('Saving to a file with new filename {}'.format(new_filename))

        initial_save_filename = "{}.{}".format(new_filename_no_extension, self.file_type)
        # Make sure you don't overwrite the existing original file
        files = list(filter(os.path.isfile, os.listdir(os.curdir)))  # files only
        save_filename = initial_save_filename
        file_versions = 1
        while save_filename in files:
            name_parts = initial_save_filename.split(".")
            save_filename = "{} ({}).{}".format(name_parts[0], file_versions, name_parts[1])
            file_versions += 1

        self.tableau_document.save_file(save_filename)
        return save_filename

# At the moment, we don't do anything with the XML of the workbook except pull out the data sources and convert into TableauDatasource objects
# The reasoning is: workbooks are vastly bigger and more complex than data sources (just look at the file sizes sometimes)
# and opening that all in memory as an XML tree would be a disadvantage in most cases given that modifying
# data source attributes is the primary use case for this library
# That said, there should probably be a mechanism for work on aspects of the workbook that we feel are useful to modify
# and also possibly a full String Replace implemented for translation purposes
class TWB(DatasourceMethods, TableauXmlFile):
    def __init__(self, filename: str, logger_obj: Optional[Logger] = None):
        TableauXmlFile.__init__(self, filename=filename, logger_obj=logger_obj)
        self._open_and_initialize(logger_obj=logger_obj)

    def _open_and_initialize(self, filename, logger_obj):
        try:

            # The file needs to be opened as string so that String methods can be used to read each line
            wb_fh = codecs.open(filename, 'r', encoding='utf-8')
            # Rather than a temporary file, open up a file-like string object
            ds_fh = io.StringIO()

            # Stream through the file, only pulling the datasources section
            ds_flag = None
            # Here we throw out metadata-records even when opening a workbook from disk, they take up space
            # and are recreate automatically.
            metadata_flag = None
            for line in wb_fh:
                # Grab the datasources

                if line.find("<metadata-records") != -1 and metadata_flag is None:
                    metadata_flag = True
                if ds_flag is True and metadata_flag is not True:
                    ds_fh.write(line)
                if line.find("<datasources") != -1 and ds_flag is None:
                    ds_flag = True
                    ds_fh.write("<datasources xmlns:user='http://www.tableausoftware.com/xml/user'>\n")
                if line.find("</metadata-records") != -1 and metadata_flag is True:
                    metadata_flag = False

                if line.find("</datasources>") != -1 and ds_flag is True:
                    ds_fh.close()
                    break
            wb_fh.close()

            # File-like object has to be reset from the start for the next read
            ds_fh.seek(0)

            # Make ElementTree read it as XML (this may be overkill left over from Python2.7)
            utf8_parser = ET.XMLParser(encoding='utf-8')
            ds_xml = ET.parse(ds_fh, parser=utf8_parser)

            # Workbook is really a shell at this point, only handles compositing the XML back prior to save time
            self.tableau_document = TableauWorkbook(twb_filename=filename, logger_obj=logger_obj)
            # This generates the data source objects that live under the TableauWorkbook, including Parameters
            self.tableau_document.build_datasource_objects(datasource_xml=ds_xml)
            #file_obj.close()
            ds_fh.close()
        except IOError:
            self.log("Cannot open file {}".format(filename))
            raise

    @property
    def file_type(self) -> str:
        return 'twb'

    @property
    def datasources(self) -> List[TableauDatasource]:
        return self.tableau_document.datasources


class TDS(DatasourceMethods, TableauXmlFile):
    def __init__(self, filename: str, logger_obj: Optional[Logger] = None):
        TableauXmlFile.__init__(self, filename=filename, logger_obj=logger_obj)
        self._open_and_initialize(filename=filename, logger_obj=logger_obj)

    def _open_and_initialize(self, filename, logger_obj):
        try:

            # The file needs to be opened as string so that String methods can be used to read each line
            o_ds_fh = codecs.open(filename, 'r', encoding='utf-8')
            # Rather than a temporary file, open up a file-like string object
            ds_fh = io.StringIO()

            # Here we throw out metadata-records even when opening a workbook from disk, they take up space
            # and are recreate automatically. Very similar to what we do in initialization of TableauWorkbook
            metadata_flag = None
            for line in o_ds_fh:
                # Grab the datasources
                if line.find("<metadata-records") != -1 and metadata_flag is None:
                    metadata_flag = True
                if metadata_flag is not True:
                    ds_fh.write(line)
                if line.find("</metadata-records") != -1 and metadata_flag is True:
                    metadata_flag = False
            o_ds_fh.close()
            # File-like object has to be reset from the start for the next read
            ds_fh.seek(0)

            # Make ElementTree read it as XML (this may be overkill left over from Python2.7)
            utf8_parser = ET.XMLParser(encoding='utf-8')
            ds_xml = ET.parse(ds_fh, parser=utf8_parser)

            self.tableau_document = TableauDatasource(datasource_xml=ds_xml.getroot(), logger_obj=logger_obj)
            ds_fh.close()
        except IOError:
            self.log("Cannot open file {}".format(filename))

    @property
    def file_type(self) -> str:
        return 'tds'

    @property
    def datasources(self) -> List[TableauDatasource]:
        return [self.tableau_document, ]

# Abstract implementation
class TableauPackagedFile(LoggingMethods, ABC):
    def __init__(self, filename: str, logger_obj: Optional[Logger] = None):
        self.logger: Optional[Logger] = logger_obj
        self.log('TableauFile initializing for {}'.format(filename))
        self.packaged_file: bool = True
        self.packaged_filename: Optional[str] = None
        self.tableau_xml_file: TableauXmlFile

        self._original_file_type: Optional[str] = None

        self.other_files: List[str] = []
        self.temp_filename: Optional[str] = None
        self.orig_filename: str = filename
        self._document_type = None

        # Internal storage for use with swapping in new files from disk at save time
        self.file_replacement_map:Optional[Dict] = None

        # Packaged up nicely but always run in constructor
        self._open_file_and_intialize(filename=filename)

    @abstractmethod
    def _open_file_and_intialize(self, filename):
        pass

    @property
    def tableau_document(self) -> Union[TableauDatasource, TableauWorkbook]:
        return self._tableau_document

    @property
    @abstractmethod
    def file_type(self) -> str:
        return self._original_file_type

    # This would be useful for interrogating Hyper files named within (should just be 1 per TDSX)
    @abstractmethod
    def get_files_in_package(self):
        pass

    # If you know a file exists in the package, you can set it for replacement during the next save
    def set_file_for_replacement(self, filename_in_package: str, replacement_filname_on_disk: str):
        # No check for file, for later if building from scratch is allowed
        self.file_replacement_map[filename_in_package] = replacement_filname_on_disk

    # Appropriate extension added if needed
    def save_new_file(self, new_filename_no_extension: str, data_file_replacement_map: Optional[Dict],
                      new_data_files_map: Optional[Dict]) -> str:
        self.start_log_block()
        new_filename = new_filename_no_extension.split('.')[0]  # simple algorithm to kill extension
        if new_filename is None:
            new_filename = new_filename_no_extension
        self.log('Saving to a file with new filename {}'.format(new_filename))
        # Change filetype if there are new extracts to add
        for ds in self.datasources:
            if ds.tde_filename is not None or new_data_files_map is not None:
                if self.file_type == 'twb':
                    self._final_file_type = 'twbx'
                    self.packaged_filename = "{}.twb".format(new_filename)
                    self.log('Final filetype will be TWBX')
                    break
                if self.file_type == 'tds' or new_data_files_map is not None:
                    self._final_file_type = 'tdsx'
                    self.packaged_filename = "{}.tds".format(new_filename)
                    self.log('Final filetype will be TDSX')
                    break

        if self._final_file_type in ['twbx', 'tdsx']:
            initial_save_filename = "{}.{}".format(new_filename, self._final_file_type)
            # Make sure you don't overwrite the existing original file
            files = list(filter(os.path.isfile, os.listdir(os.curdir)))  # files only
            save_filename = initial_save_filename
            file_versions = 1
            while save_filename in files:
                name_parts = initial_save_filename.split(".")
                save_filename = "{} ({}).{}".format(name_parts[0],file_versions, name_parts[1])
                file_versions += 1
            new_zf = zipfile.ZipFile(save_filename, 'w', zipfile.ZIP_DEFLATED)
            # Save the object down
            self.log('Creating temporary XML file {}'.format(self.packaged_filename))
            # Have to extract the original TWB to temporary file
            self.log('Creating from original file {}'.format(self.orig_filename))
            if self._original_file_type == 'twbx':
                file_obj = open(self.orig_filename, 'rb')
                o_zf = zipfile.ZipFile(file_obj)
                o_zf.extract(self.tableau_document.twb_filename)
                shutil.copy(self.tableau_document.twb_filename, 'temp.twb')
                os.remove(self.tableau_document.twb_filename)
                self.tableau_document.twb_filename = 'temp.twb'
                file_obj.close()

            # Call to the tableau_document object to write the Tableau XML
            self.tableau_document.save_file(self.packaged_filename)
            new_zf.write(self.packaged_filename)
            self.log('Removing file {}'.format(self.packaged_filename))
            os.remove(self.packaged_filename)

            if self._original_file_type == 'twbx':
                os.remove('temp.twb')
                self.log('Removed file temp.twb'.format(self.packaged_filename))

            temp_directories_to_remove = {}

            if len(self.other_files) > 0:
                file_obj = open(self.orig_filename, 'rb')
                o_zf = zipfile.ZipFile(file_obj)

                # Find datasources with new extracts, and skip their files
                extracts_to_skip = []
                for ds in self.tableau_document.datasources:
                    if ds.existing_tde_filename is not None and ds.tde_filename is not None:
                        extracts_to_skip.append(ds.existing_tde_filename)

                for filename in self.other_files:
                    self.log('Looking into additional files: {}'.format(filename))

                    # Skip extracts listed for replacement
                    if filename in extracts_to_skip:
                        self.log('File {} is from an extract that has been replaced, skipping'.format(filename))
                        continue

                    # If file is listed in the data_file_replacement_map, write data from the mapped in file
                    if data_file_replacement_map and filename in data_file_replacement_map:
                        new_zf.write(data_file_replacement_map[filename], "/" + filename)
                        # Delete from the data_file_replacement_map to reduce down to end
                        del data_file_replacement_map[filename]
                    else:
                        o_zf.extract(filename)
                        new_zf.write(filename)
                        os.remove(filename)
                    self.log('Removed file {}'.format(filename))
                    lowest_level = filename.split('/')
                    temp_directories_to_remove[lowest_level[0]] = True
                file_obj.close()

            # Loop through remaining files in data_file_replacement_map to just add
            for filename in new_data_files_map:
                new_zf.write(new_data_files_map[filename], "/" + filename)

            # If new extract, write that file
            for ds in self.tableau_document.datasources:
                if ds.tde_filename is not None:
                    new_zf.write(ds.tde_filename, '/Data/Datasources/{}'.format(ds.tde_filename))
                    os.remove(ds.tde_filename)
                    self.log('Removed file {}'.format(ds.tde_filename))

            # Cleanup all the temporary directories
            for directory in temp_directories_to_remove:
                self.log('Removing directory {}'.format(directory))
                try:
                    shutil.rmtree(directory)
                except OSError as e:
                    # Just means that directory didn't exist for some reason, probably a swap occurred
                    pass
            new_zf.close()

            return save_filename
        else:
            initial_save_filename = "{}.{}".format(new_filename_no_extension, self.file_type)
            # Make sure you don't overwrite the existing original file
            files = list(filter(os.path.isfile, os.listdir(os.curdir)))  # files only
            save_filename = initial_save_filename
            file_versions = 1
            while save_filename in files:
                name_parts = initial_save_filename.split(".")
                save_filename = "{} ({}).{}".format(name_parts[0],file_versions, name_parts[1])
                file_versions += 1

            self.tableau_document.save_file(save_filename)
            return save_filename




class TDSX(DatasourceMethods, TableauPackagedFile):

    def _open_file_and_intialize(self, filename):
        try:
            file_obj = open(filename, 'rb')
            self.log('File type is {}'.format(self.file_type))
            # Extract the TWB or TDS file to disk, then create a sub TableauFile

            self.zf = zipfile.ZipFile(file_obj)
            # Ignore anything in the subdirectories
            for name in self.zf.namelist():
                if name.find('/') == -1:
                    if name.endswith('.tds'):
                        self.log('Detected a TDS file in archive, saving temporary file')
                        self.packaged_filename = os.path.basename(self.zf.extract(name))
                else:
                    self.other_files.append(name)

            self.tableau_xml_file = TDS(self.packaged_filename, self.logger)
            self._tableau_document = self.tableau_xml_file.tableau_document

            self.xml_name = None
            file_obj.close()
        except IOError:
            self.log("Cannot open file {}".format(filename))
            raise

    @property
    def datasources(self) -> List[TableauDatasource]:
        return [self._tableau_document, ]

    @property
    def file_type(self) -> str:
        return 'tdsx'

    @property
    def tableau_document(self) -> TableauDatasource:
        return self._tableau_document

    # This would be useful for interrogating Hyper files named within (should just be 1 per TDSX)
    def get_files_in_package(self):
        pass

    # Appropriate extension added if needed
    def save_new_file(self, new_filename_no_extension: str, data_file_replacement_map: Optional[Dict],
                      new_data_files_map: Optional[Dict]) -> str:
        self.start_log_block()
        new_filename = new_filename_no_extension.split('.')[0]  # simple algorithm to kill extension
        if new_filename is None:
            new_filename = new_filename_no_extension
        self.log('Saving to a file with new filename {}'.format(new_filename))

        initial_save_filename = "{}.{}".format(new_filename, self._final_file_type)
        # Make sure you don't overwrite the existing original file
        files = list(filter(os.path.isfile, os.listdir(os.curdir)))  # files only
        save_filename = initial_save_filename
        file_versions = 1
        while save_filename in files:
            name_parts = initial_save_filename.split(".")
            save_filename = "{} ({}).{}".format(name_parts[0],file_versions, name_parts[1])
            file_versions += 1
        new_zf = zipfile.ZipFile(save_filename, 'w', zipfile.ZIP_DEFLATED)
        # Save the object down
        self.log('Creating temporary XML file {}'.format(self.packaged_filename))
        # Have to extract the original TWB to temporary file
        self.log('Creating from original file {}'.format(self.orig_filename))
        if self._original_file_type == 'twbx':
            file_obj = open(self.orig_filename, 'rb')
            o_zf = zipfile.ZipFile(file_obj)
            o_zf.extract(self.tableau_document.twb_filename)
            shutil.copy(self.tableau_document.twb_filename, 'temp.twb')
            os.remove(self.tableau_document.twb_filename)
            self.tableau_document.twb_filename = 'temp.twb'
            file_obj.close()

        # Call to the tableau_document object to write the Tableau XML
        self.tableau_document.save_file(self.packaged_filename)
        new_zf.write(self.packaged_filename)
        self.log('Removing file {}'.format(self.packaged_filename))
        os.remove(self.packaged_filename)

        temp_directories_to_remove = {}

        if len(self.other_files) > 0:
            file_obj = open(self.orig_filename, 'rb')
            o_zf = zipfile.ZipFile(file_obj)

            # Find datasources with new extracts, and skip their files
            extracts_to_skip = []
            for ds in self.tableau_document.datasources:
                if ds.existing_tde_filename is not None and ds.tde_filename is not None:
                    extracts_to_skip.append(ds.existing_tde_filename)

            for filename in self.other_files:
                self.log('Looking into additional files: {}'.format(filename))

                # Skip extracts listed for replacement
                if filename in extracts_to_skip:
                    self.log('File {} is from an extract that has been replaced, skipping'.format(filename))
                    continue

                # If file is listed in the data_file_replacement_map, write data from the mapped in file
                if data_file_replacement_map and filename in data_file_replacement_map:
                    new_zf.write(data_file_replacement_map[filename], "/" + filename)
                    # Delete from the data_file_replacement_map to reduce down to end
                    del data_file_replacement_map[filename]
                else:
                    o_zf.extract(filename)
                    new_zf.write(filename)
                    os.remove(filename)
                self.log('Removed file {}'.format(filename))
                lowest_level = filename.split('/')
                temp_directories_to_remove[lowest_level[0]] = True
            file_obj.close()

        # Loop through remaining files in data_file_replacement_map to just add
        for filename in new_data_files_map:
            new_zf.write(new_data_files_map[filename], "/" + filename)

        # DEPRECATED
        # If new extract, write that file
        #or ds in self.tableau_document.datasources:
        #    if ds.tde_filename is not None:
        #        new_zf.write(ds.tde_filename, '/Data/Datasources/{}'.format(ds.tde_filename))
        #        os.remove(ds.tde_filename)
        #        self.log('Removed file {}'.format(ds.tde_filename))

        # Cleanup all the temporary directories
        for directory in temp_directories_to_remove:
            self.log('Removing directory {}'.format(directory))
            try:
                shutil.rmtree(directory)
            except OSError as e:
                # Just means that directory didn't exist for some reason, probably a swap occurred
                pass
        new_zf.close()

        return save_filename



class TWBX(DatasourceMethods, TableauPackagedFile):

    #self._open_file_and_intialize(filename=filename)

    def _open_file_and_intialize(self, filename):
        try:
            file_obj = open(filename, 'rb')
            self.log('File type is {}'.format(self.file_type))
            # Extract the TWB or TDS file to disk, then create a sub TableauFile

            self.zf = zipfile.ZipFile(file_obj)
            # Ignore anything in the subdirectories
            for name in self.zf.namelist():
                if name.find('/') == -1:
                    if name.endswith('.twb'):
                        self.log('Detected a TWB file in archive, saving temporary file')
                        self.packaged_filename = os.path.basename(self.zf.extract(name))
                else:
                    self.other_files.append(name)

            self.tableau_xml_file = TWB(self.packaged_filename, self.logger)
            # self._tableau_document = self.tableau_xml_file._tableau_document

            file_obj.close()
        except IOError:
            self.log("Cannot open file {}".format(filename))
            raise

    @property
    def datasources(self) -> List[TableauDatasource]:
        return self._tableau_document.datasources

    @property
    def tableau_document(self) -> TableauWorkbook:
        return self._tableau_document


class TFL(TableauXmlFile):

    @property
    def file_type(self) -> str:
        return 'tfl'

class TFLX(TableauPackagedFile):

    @property
    def file_type(self) -> str:
        return 'tflx'