# rnggui.py - MainWindow of Reportbug-NG.
# Copyright (C) 2007-2014  Bastian Venthur
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import logging
import _thread

from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import QCoreApplication

from ui import mainwindow
from ui import submitdialog
import rnghelpers as rng
import debianbts as bts
from rngsettingsdialog import RngSettingsDialog
import bug


def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i+n]


class RngGui(QtWidgets.QMainWindow, mainwindow.Ui_MainWindow):

    def __init__(self, args):
        QtWidgets.QMainWindow.__init__(self)
        self.setupUi(self)

        self.logger = logging.getLogger("RngGui")
        self.logger.info("Logger initialized.")

        # Since this is not possible withon qtcreator
        self.toolButton.setDefaultAction(self.actionClearLineEdit)

        #
        self.progressbar = QtWidgets.QProgressBar(self.statusbar)
        self.progressbar.setFixedHeight(20)
        self.progressbar.setFixedWidth(100)
        self.progressbar.hide()
        self.statusbar.addPermanentWidget(self.progressbar)

        self.actionNewBugreport.triggered.connect(self.new_bugreport)
        self.actionAdditionalInfo.triggered.connect(self.additional_info)
        self.actionCloseBugreport.triggered.connect(self.close_bugreport)
        self.actionNewWnpp.triggered.connect(self.new_wnpp)
        self.actionClearLineEdit.triggered.connect(self.clear_lineedit)
        self.actionSettings.triggered.connect(self.settings_diag)
        self.actionAbout.triggered.connect(self.about)
        self.actionAboutQt.triggered.connect(self.about_qt)
        self.lineEdit.textChanged.connect(self.lineedit_text_changed)
        self.lineEdit.returnPressed.connect(self.lineedit_return_pressed)
        self.tableView.activated.connect(self.activated)
        self.webView.loadProgress.connect(self.load_progress)
        self.webView.loadStarted.connect(self.load_started)
        self.webView.loadFinished.connect(self.load_finished)
        self.checkBox.clicked.connect(self.checkbox_clicked)

        # setup the table
        self.model = TableModel(self)
        self.proxymodel = MySortFilterProxyModel(self)
        self.proxymodel.setFilterKeyColumn(-1)
        self.proxymodel.setDynamicSortFilter(True)
        self.proxymodel.setSourceModel(self.model)
        self.tableView.setModel(self.proxymodel)
        self.tableView.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.tableView.verticalHeader().setVisible(False)

        # setup the settings
        self.settings = rng.Settings(rng.Settings.CONFIGFILE)
        self.settings.load()
        self._apply_settings()
        self.webView.setHtml(rng.getRngInstructions())

        # setup the finite state machine
        self._stateChanged(None, None)

        if args:
            self.lineEdit.setText(str(args[0]))
            self.lineedit_return_pressed()


    def closeEvent(self, ce):
        """Save the settings and close the GUI."""
        self.logger.info("Catched close event.")
        self._get_settings()
        self.settings.save()
        ce.accept()


    def activated(self, index):
        """React on click in table."""
        self.logger.info("Row %s activated." % str(index.row()))
        realrow = self.proxymodel.mapToSource(index).row()
        bugnr = self.model.elements[realrow].bug_num
        # find the bug in our list, and get the package and nr
        for i in self.bugs:
            if i.bug_num == bugnr:
                self.currentBug = i
                break
        self._stateChanged(self.currentBug.package, self.currentBug)
        url = bts.BTS_URL + str(bugnr)
        self._show_url(url)


    def new_bugreport(self):
        self.logger.info("New Bugreport.")
        self.__submit_dialog("newbug")


    def additional_info(self):
        self.logger.info("Additional Info.")
        self.__submit_dialog("moreinfo")


    def close_bugreport(self):
        self.logger.info("Close Bugreport.")
        self.__submit_dialog("close")


    def new_wnpp(self):
        self.logger.info("New WNPP.")
        self.__submit_dialog("wnpp")


    def clear_lineedit(self):
        self.logger.info("Clear Lineedit.")
        self.lineEdit.clear()


    def lineedit_text_changed(self, text):
        self.logger.info("Text changed: %s" % text)
        text = str(text)
        self.proxymodel.setFilterRegExp(\
            QtCore.QRegExp(text,
                           QtCore.Qt.CaseInsensitive,
                           QtCore.QRegExp.FixedString)
            )
        self.tableView.resizeRowsToContents()


    def lineedit_return_pressed(self):
        #
        # just in case ;)
        #
        text = str(self.lineEdit.text())
        if text.startswith("http://"):
            self._show_url(text)
            return
        if len(text) == 0:
            return

        self.logger.info("Return pressed.")
        self.lineEdit.clear()
        # TODO: self.lineEdit.clear() does not always work, why?
        #QtCore.QTimer.singleShot(0,self.lineEdit,QtCore.SLOT("clear()"))
        query = rng.translate_query(text)
        self.logger.debug("Query: %s" % str(query))

        # test if there is a submit-as field available and rename the packages
        # if nececesairy
        for i in range(0, len(query), 2):
            if query[i] == 'package':
                realname = bug.submit_as(query[i+1])
                if query[i+1] != realname:
                    self.logger.debug("Using %s as package name as requested by developer." % str(realname))
                    query[i+1] = realname
        # Single bug or list of bugs?
        if query[0]:
            buglist = bts.get_bugs(query)
        else:
            buglist = [query[1]]
        # ok, we know the package, so enable some buttons which don't depend
        # on the existence of the acutal packe (wnpp) or bugreports for that
        # package.
        if query[0] in ("src", "package"):
            self._stateChanged(query[1], None)
        # if we got a bugnumber we'd like to select it and enable some more
        # buttons. unfortunately we don't know if the bugnumber actually exists
        # for now, so we have to wait a bit until the bug is fetched.
        else:
            self._stateChanged(None, None)
        self.logger.debug("Buglist matching the query: %s" % str(buglist))
        chunksize = 50
        if len(buglist) > chunksize:
            self.load_started()
            self.logger.debug("Buglist longer than %i, splitting in chunks." % chunksize)
            self.bugs = []
            i = 0
            for chunk in chunks(buglist, chunksize):
                i += 1
                progress = int(100. * i * chunksize / len(buglist))
                if progress > 100:
                    progress = 100
                self.load_progress(progress)
                bl = bts.get_status(chunk)
                if len(bl) == 0:
                    self.logger.error("One of the following bugs caused the BTS to hickup: %s" % str(bl))
                self.bugs.extend(bl)
            self.load_finished(True)
        else:
            self.bugs = bts.get_status(buglist)
        # ok, we fetched the bugs. see if the list isn't empty
        if query[0] in (None,) and len(self.bugs) > 0:
            self.currentBug = self.bugs[0]
            self.currentPackage = self.currentBug.package
            self._stateChanged(self.currentPackage, self.currentBug)
        self.model.set_elements(self.bugs)
        self.tableView.resizeRowsToContents()


    def settings_diag(self):
        """Spawn settings dialog and get settings."""
        s = RngSettingsDialog(self.settings)
        if s.exec_() == s.Accepted:
            self.logger.debug("Accepted settings change, applying.")
            self.settings = s.settings


    def about(self):
        """Shows the about box."""
        # TODO: copyright string below should be a constant
        QtWidgets.QMessageBox.about(\
            self,
            self.tr("About Reportbug-NG"),"""Reportbug-NG """ +
                rng.getInstalledPackageVersion("reportbug-ng") + """\n""" +
            self.tr(\
"""Reportbug-NG is a graphical interface for searching, filtering, reporting
or manipulating bugs in Debian's Bug Tracking System.""") + """\n""" +
            self.tr(\
"""Copyright (C) 2007-2014 Bastian Venthur <venthur at debian org>

Homepage: http://reportbug-ng.alioth.debian.org

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version."""))


    def about_qt(self):
        QtWidgets.QMessageBox.aboutQt(self, self.tr("About Qt"))


    def _stateChanged(self, package, bug):
        """Transition for our finite state machine logic"""
        if package:
            self.currentPackage = package
            self.actionNewBugreport.setEnabled(1)
        else:
            self.currentPackage = ""
            self.actionNewBugreport.setEnabled(0)

        if bug:
            self.currentBug = bug
            self.actionAdditionalInfo.setEnabled(1)
            self.actionCloseBugreport.setEnabled(1)
        else:
            self.currentBug = bts.Bugreport()
            self.actionAdditionalInfo.setEnabled(0)
            self.actionCloseBugreport.setEnabled(0)


    def __submit_dialog(self, type):
        """Setup and spawn the submit dialog."""
        dialog = SubmitDialog()
        dialog.checkBox_script.setChecked(self.settings.script)
        dialog.checkBox_presubj.setChecked(self.settings.presubj)

        if type == 'wnpp':
            dialog.wnpp_groupBox.setEnabled(1)
            dialog.wnpp_groupBox.setChecked(1)
            dialog.groupBox_other.setEnabled(0)
            package = self.currentPackage
            to = "submit@bugs.debian.org"
        elif type == 'newbug':
            dialog.wnpp_groupBox.setEnabled(1)
            dialog.wnpp_groupBox.setChecked(0)
            package = self.currentPackage
            to = "submit@bugs.debian.org"
        elif type == 'moreinfo':
            dialog.wnpp_groupBox.setEnabled(0)
            dialog.comboBoxSeverity.setEnabled(0)
            dialog.checkBoxSecurity.setEnabled(0)
            dialog.checkBoxPatch.setEnabled(0)
            dialog.checkBoxL10n.setEnabled(0)
            package = self.currentBug.package
            to = "%s@bugs.debian.org" % self.currentBug.bug_num
        elif type == 'close':
            dialog.groupBox_other.setEnabled(0)
            dialog.wnpp_groupBox.setEnabled(0)
            dialog.comboBoxSeverity.setEnabled(0)
            dialog.checkBoxSecurity.setEnabled(0)
            dialog.checkBoxPatch.setEnabled(0)
            dialog.checkBoxL10n.setEnabled(0)
            dialog.lineEditSummary.setText("Done: %s" % self.currentBug.subject)
            package = self.currentBug.package
            to = "%s-done@bugs.debian.org" % self.currentBug.bug_num
        else:
            self.logger.critical("Received unknown submit dialog type!")

        version = rng.getInstalledPackageVersion(package)
        dialog.lineEditPackage.setText(package)
        dialog.lineEditVersion.setText(version)
        for action in rng.WNPP_ACTIONS:
            dialog.wnpp_comboBox.addItem(action)
        for sev in rng.SEVERITY:
            dialog.comboBoxSeverity.addItem(sev)
        # Set default severity to 'normal'
        dialog.comboBoxSeverity.setCurrentIndex(4)

        # Run the dialog
        if dialog.exec_() == dialog.Accepted:
            package = dialog.lineEditPackage.text()
            version = dialog.lineEditVersion.text()
            severity = str(dialog.comboBoxSeverity.currentText()).lower()
            tags = []
            cc = []
            if dialog.checkBoxL10n.isChecked():
                tags.append("l10n")
            if dialog.checkBoxPatch.isChecked():
                tags.append("patch")
            if dialog.checkBoxSecurity.isChecked():
                tags.append("security")
                cc.append("secure-testing-team@lists.alioth.debian.org")
            mua = self.settings.lastmua
            script = dialog.checkBox_script.isChecked()
            presubj = dialog.checkBox_presubj.isChecked()

            body, subject = '', ''
            # WNPP Bugreport
            if dialog.wnpp_comboBox.isEnabled():
                action = dialog.wnpp_comboBox.currentText()
                descr = dialog.wnpp_lineEdit.text()
                body = rng.prepare_wnpp_body(action, package, version)
                subject = rng.prepare_wnpp_subject(action, package, descr)
            # Closing a bug
            elif type == 'close':
                severity = ""
                subject = str(dialog.lineEditSummary.text())
                body = rng.prepare_minimal_body(package, version, severity, tags, cc)
            # New or moreinfo
            else:
                if type == 'moreinfo':
                    severity = ""
                subject = str("[%s] %s" % (package, dialog.lineEditSummary.text()))
                body = rng.prepareBody(package, version, severity, tags, cc, script)

            if len(subject) == 0:
                subject = "Please enter a subject before submitting the report."

            if presubj:
                txt = rng.get_presubj(package)
                if txt:
                    QtWidgets.QMessageBox.information(self, "Information", txt)
            _thread.start_new_thread(rng.prepareMail, (mua, to, subject, body))


    def _apply_settings(self):
        """Apply settings."""
        self.resize(self.settings.width, self.settings.height)
        self.move(self.settings.x, self.settings.y)
        self.tableView.horizontalHeader().resizeSection(0, self.settings.bugnrWidth)
        self.tableView.horizontalHeader().resizeSection(1, self.settings.packageWidth)
        self.tableView.horizontalHeader().resizeSection(2, self.settings.summaryWidth)
        self.tableView.horizontalHeader().resizeSection(3, self.settings.statusWidth)
        self.tableView.horizontalHeader().resizeSection(4, self.settings.severityWidth)
        self.tableView.horizontalHeader().resizeSection(5, self.settings.lastactionWidth)
        order = QtCore.Qt.DescendingOrder
        if self.settings.sortAsc:
            order = QtCore.Qt.AscendingOrder
        self.tableView.setSortingEnabled(True)
        self.tableView.sortByColumn(self.settings.sortByCol, order)
        self.checkBox.setChecked(self.settings.hideClosedBugs)


    def _get_settings(self):
        """Get current settings."""
        p = self.pos()
        s = self.size()
        self.settings.x = p.x()
        self.settings.y = p.y()
        self.settings.width = s.width()
        self.settings.height = s.height()
        self.settings.sortByCol = self.tableView.horizontalHeader().sortIndicatorSection()
        self.settings.sortAsc = {QtCore.Qt.AscendingOrder : True,
                                 QtCore.Qt.DescendingOrder : False}[self.tableView.horizontalHeader().sortIndicatorOrder()]
        self.settings.bugnrWidth = self.tableView.columnWidth(0)
        self.settings.packageWidth = self.tableView.columnWidth(1)
        self.settings.summaryWidth = self.tableView.columnWidth(2)
        self.settings.statusWidth = self.tableView.columnWidth(3)
        self.settings.severityWidth = self.tableView.columnWidth(4)
        self.settings.lastactionWidth = self.tableView.columnWidth(5)
        self.settings.hideClosedBugs = self.checkBox.isChecked()


    def _show_url(self, url):
        url = QtCore.QUrl(url)
        self.webView.setUrl(url)


    def load_started(self):
        """Webwiew started to load a page."""
        self.progressbar.show()


    def load_progress(self, progress):
        """Webwiew progress advanced."""
        self.progressbar.setValue(progress)


    def load_finished(self, ok):
        """Webview finished do load the page."""
        self.progressbar.reset()
        self.progressbar.hide()


    def checkbox_clicked(self, check):
        """Checkbox to toggle hide/show closed Bugs was changed."""
        self.settings.hideClosedBugs = check
        self.proxymodel.invalidate()


class TableModel(QtCore.QAbstractTableModel):

    def __init__(self, parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.parent = parent
        self.logger = logging.getLogger("TableModel")
        self.elements = []
        self.header = [QCoreApplication.translate('TableModel', "Bugnumber"),
                       QCoreApplication.translate('TableModel', "Package"),
                       QCoreApplication.translate('TableModel', "Summary"),
                       QCoreApplication.translate('TableModel', "Status"),
                       QCoreApplication.translate('TableModel', "Severity"),
                       QCoreApplication.translate('TableModel', "Tags"),
                       QCoreApplication.translate('TableModel', "Last Action")]


    def rowCount(self, parent):
        return len(self.elements)


    def columnCount(self, parent):
        return len(self.header)


    #
    # DAMMIT DONT IGNORE THE DISPLAY ROLE!!
    #
    def data(self, index, role):
        if not index.isValid():
            return QtCore.QVariant()
        if role == QtCore.Qt.ForegroundRole:
            severity = self.elements[index.row()].severity.lower()
            done = self.elements[index.row()].done
            c = self.parent.settings.c_normal
            if severity == "grave":
                c = self.parent.settings.c_grave
            elif severity == "serious":
                c = self.parent.settings.c_serious
            elif severity == "critical":
                c = self.parent.settings.c_critical
            elif severity == "important":
                c = self.parent.settings.c_important
            elif severity == "minor":
                c = self.parent.settings.c_minor
            elif severity == "wishlist":
                c = self.parent.settings.c_wishlist
            if done:
                c = self.parent.settings.c_resolved
            return QtCore.QVariant(QtGui.QColor(c))
        if role != QtCore.Qt.DisplayRole:
            return QtCore.QVariant()
        bug = self.elements[index.row()]
        if bug.archived:
            status = "Archived"
        elif bug.done:
            status = "Closed"
        else:
            status = "Open"
        data = {0 : bug.bug_num,
                1 : bug.package,
                2 : bug.subject,
                3 : status,
                4 : bug.severity,
                5 : ", ".join(bug.tags),
                6 : QtCore.QDate(bug.log_modified)}[index.column()]
        return QtCore.QVariant(data)


    #
    # DAMMIT DONT IGNORE THE DISPLAY ROLE!!
    #
    def headerData(self, section, orientation, role):
        if role != QtCore.Qt.DisplayRole:
            return QtCore.QVariant()
        if orientation == QtCore.Qt.Horizontal:
            return QtCore.QVariant(self.header[section])
        else:
            return QtCore.QVariant()


    def set_elements(self, entries):
        self.logger.info("Setting Elements.")
        self.beginRemoveRows(QtCore.QModelIndex(), 0, len(self.elements)-1)
        self.elements = []
        self.endRemoveRows()
        self.beginInsertRows(QtCore.QModelIndex(), 0, len(entries)-1)
        self.elements = entries
        self.endInsertRows()


class MySortFilterProxyModel(QtCore.QSortFilterProxyModel):

    def __init__(self, parent=None):
        QtCore.QSortFilterProxyModel.__init__(self, parent)
        self.logger = logging.getLogger("MySortFilterProxyModel")
        self.parent = parent


    def lessThan(self, left, right):
        if left.column() != 4:
            return QtCore.QSortFilterProxyModel.lessThan(self, left, right)
        l = self.sourceModel().elements[left.row()]
        r = self.sourceModel().elements[right.row()]
        return l < r


    def filterAcceptsRow(self, sourceRow, sourceParent):
        if self.sourceModel().elements[sourceRow].done and self.parent.settings.hideClosedBugs:
            return False
        return QtCore.QSortFilterProxyModel.filterAcceptsRow(self, sourceRow, sourceParent)


class SubmitDialog(QtWidgets.QDialog, submitdialog.Ui_SubmitDialog):

    def __init__(self):
        QtWidgets.QDialog.__init__(self)
        self.setupUi(self)
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).clicked.connect(self.accept)
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Cancel).clicked.connect(self.reject)
        self.comboBoxSeverity.currentIndexChanged.connect(self.severity_changed)

    def severity_changed(self, index):
        self.label_severity.setText(rng.getSeverityExplanation(index))

