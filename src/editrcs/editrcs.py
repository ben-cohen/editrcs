#!/usr/bin/python
############################################################################
# EditRCS: Python library to read, manipulate and write RCS ,v files
#
# Copyright (C) 2014 Ben Cohen
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
############################################################################

"""EditRCS: Python library to read, manipulate and write RCS ,v files

EditRCS is a library to with functions to read RCS files into Python
classes Rcs and RcsDelta, and to manipulate them and write them to a new
RCS file.

It is intended to be used to manipulate RCS files in ways that the RCS tools
don't support, but it requires some knowledge of how RCS files work rather
than being a polished command-line tool.

See the rcsfile(5) manpage for RCS file format definition.  See also
https://www.gnu.org/software/rcs/manual/ and
http://www.gnu.org/software/rcs/tichy-paper.pdf

Limitations: I'm going with the 5.9.2 version of the manpage, and ignoring 
the newphrase in the earlier (e.g. 5.6) specifications for now.
It is written to be simple rather than optimised for speed or space."""

import re
import os
import sys
from threading import Thread

############################################################################
# Utility functions
############################################################################

def IsVisibleChar(c):
    """Return whether the character c is a visible character, as defined in 
    rcsfile(5)."""
    return 33 <= ord(c) <= 126 or 160 <= ord(c) <= 377


def IsWhitespaceChar(c):
    """Return whether the character c is a whitespace character, as defined in 
    rcsfile(5)."""
    return 8 <= ord(c) <= 13 or ord(c) == 32


def AddAtQuoting(s):
    """Return the string s quoted for RCS, i.e. delimited by the at symbol '@'
    with any at symbols doubled."""
    return '@' + s.replace('@', '@@') + '@'


def RemoveAtQuoting(s):
    """Return the string s with RCS at quoting removed."""
    assert(s[0] == '@' and s[-1] == '@')    
    return s[1:-1].replace('@@', '@')


def NumToList(s):
    """Return a list of the components of the dotted RCS number s."""
    return map(lambda v: int(v), s.split('.'))


def ListToNum(l):
    """Return the dotted RCS number whose elements are those in the list l."""
    return ".".join(map(lambda v: str(v), l))


def IncrementNum(num, delta):
    """Given dotted RCS numbers num and delta, return the dotted RCS number 
    formed by adding components of delta to num, starting from the left.  Delta
    must not have more elements than num."""
    if num == None or num == "":
        return num
    num_v = NumToList(num)
    delta_v = NumToList(delta)
    assert len(delta_v) <= len(num_v)
    for i in range(0, len(num_v)):
        num_v[i] += delta_v[i]
    return ListToNum(num_v)


def DecrementNum(num, delta):
    """Given dotted RCS numbers num and delta, return the dotted RCS number 
    formed by subtracting components of delta from num, starting from the left.
    Delta must not have more elements than num."""
    if num == None or num == "":
        return num
    num_v = NumToList(num)
    delta_v = NumToList(delta)
    assert len(delta_v) <= len(num_v)
    for i in range(0, len(num_v)):
        num_v[i] -= delta_v[i]
    return ListToNum(num_v)


def StringToDate(s):
    """For a dotted RCS date s, return the corresponding 6-tuple
    (year, month, day, hour, minute, second)."""
    m = re.search("^(\d\d|\d\d\d\d).(\d\d).(\d\d).(\d\d).(\d\d).(\d\d)$", s)
    assert(m != None)

    (Y, MM, DD, hh, mm, ss) = m.groups()
    Y = int(Y)
    MM = int(MM)
    DD = int(DD)
    hh = int(hh)
    mm = int(mm)
    ss = int(ss)

    if not (0 <= Y < 100 or 2000 <= Y):
        raise RcsError("Invalid year value in date %s"%s)
    if not 1 <= MM <= 12:
        raise RcsError("Invalid month value in date %s"%s)
    if not 1 <= DD <= 31:
        raise RcsError("Invalid day value in date %s"%s)
    if not 0 <= hh <= 23:
        raise RcsError("Invalid hour value in date %s"%s)
    if not 0 <= mm <= 59:
        raise RcsError("Invalid minute value in date %s"%s)
    if not 0 <= ss <= 60:      # ss can be 60 according to rcsfile5
        raise RcsError("Invalid second value in date %s"%s)
    
    if Y < 100:
        Y += 1900
    return (Y, MM, DD, hh, mm, ss)


def DateToString(Y, MM, DD, hh, mm, ss):
    """For a 6-tuple (year, month, day, hour, minute, second) date, return the
    corresponding dotted RCS date."""
    if not Y >= 1900:
        raise RcsError("Invalid year value in date %s"%[Y, MM, DD, hh, mm, ss])
    if not 1 <= MM <= 12:
        raise RcsError("Invalid month value in date %s"%[Y, MM, DD, hh, mm, ss])
    if not 1 <= DD <= 31:
        raise RcsError("Invalid day value in date %s"%[Y, MM, DD, hh, mm, ss])
    if not 0 <= hh <= 23:
        raise RcsError("Invalid hour value in date %s"%[Y, MM, DD, hh, mm, ss])
    if not 0 <= mm <= 59:
        raise RcsError("Invalid minute value in date %s"%
                       [Y, MM, DD, hh, mm, ss])
    if not 0 <= ss <= 60:      # ss can be 60 according to rcsfile5
        raise RcsError("Invalid second value in date %s"%
                       [Y, MM, DD, hh, mm, ss])
    
    if (Y < 2000):
        Y = "%02d"%(Y - 1900)
    else:
        Y = "%04d"%Y
     
    return "%s.%02d.%02d.%02d.%02d.%02d"%(Y, MM, DD, hh, mm, ss)


def StringColonMapToMap(s):
    """Turn a {sym:num}* or {id:num}* white-space separated list into a map
    with the sym/id components as keys and the num components as values."""
    lex = Lexer(s)
    ret = {}
    while True:
        # A sym is also an id so we only need to check for the latter
        sym = lex.getId(False)
        if sym == None:
            break
        lex.getColon()
        num = lex.getNum()
        ret[sym] = num
    return ret


def MapToStringColonMap(m):
    """Turn a map where the keys are RCS syms/ids and the values are RCS nums
    into a {sym:num}* or {id:num}* white-space separated list."""
    ret = ""
    for k in m.keys():
        v = m[k]
        if ret == "":
            ret = "%s:%s"%(k,v)
        else:
            ret += " %s:%s"%(k,v)
    return ret


def StringNumsToList(s):
    """Turn a string containing a whitespace separated list of RCS numbers into
    a Python list."""
    lex = Lexer(s)
    ret = []
    while True:
        num = lex.getNum(False)
        if num == None:
            break
        ret.append(num)
    return ret


def ListToStringNums(m):
    """Turn a Python list of RCS numbers into a string containing a whitespace 
    separated list."""
    ret = ""
    for n in m:
        if ret == "":
            ret = "%s"%(n)
        else:
            ret += " %s"%(n)
    return ret


def TextToDiff(source, dest):
    """Given strings containing a source and destination revision return a    
    string containing an RCS-style diff."""
    # Use diff's RCS output option
    (src_r, src_w) = os.pipe()
    (dst_r, dst_w) = os.pipe()
    (res_r, res_w) = os.pipe()
    if os.fork() == 0:
        # Child
        os.close(src_w)
        os.close(dst_w)
        os.close(res_r)
        os.dup2(res_w, sys.stdout.fileno())
        os.execlp("diff",
                  "diff",
                  "-n",
                  "/dev/fd/%d"%src_r,
                  "/dev/fd/%d"%dst_r)

    # Parent
    os.close(src_r)
    os.close(dst_r)
    os.close(res_w)
    src_w = os.fdopen(src_w, 'w')
    dst_w = os.fdopen(dst_w, 'w')
    res_r = os.fdopen(res_r, 'r')

    def FeederThread(f, file):
        f.write(file)
        f.close()

    src_t = Thread(target = FeederThread, args = (src_w, source))
    src_t.start()
    dst_t = Thread(target = FeederThread, args = (dst_w, dest))
    dst_t.start()
    result = res_r.read()
    src_t.join()
    dst_t.join()
    res_r.close()

    return result


def TextFromDiff(source, diff):
    """Given strings containing a source revision and an RCS-style diff, apply
    the diff to the source revision and return the resulting string."""
    # Parse RCS-style diff and apply it
    remdiff = diff
    offset = -1     # "diff -n" is 1-based
    source = source.split('\n')   # need to keep any terminal '\n'
    while True:
        if len(remdiff) > 1:
            (s, remdiff) = remdiff.split('\n', 1)
        else:
            s = remdiff
        if re.search("^\s*$", s) != None:
            break
        res = re.search("^([ad])([0-9]+)\s+([0-9]+)\s*$", s)
        if res == None:
            raise RcsError("Invalid rcsdiff command '%s'"%s)
        (c, start, numlines) = res.groups()
        start = int(start)
        numlines = int(numlines)
        if c == 'd':
            fromline = start + offset
            toline = fromline + numlines
            if fromline < 0 or fromline >= len(source):
                raise RcsError("fromline has gone wrong")
            if toline < 0 or toline >= len(source):
                raise RcsError("toline has gone wrong")
            source = source[0:fromline] + source[toline:]
            offset -= numlines
        elif c == 'a':
            fromline = start + offset + 1
            split = remdiff.split('\n', numlines)
            add = split[:-1]
            remdiff = split[-1]
            if fromline < 0 or fromline >= len(source):
                raise RcsError("fromline has gone wrong")
            source = source[0:fromline] + add + source[fromline:]
            offset += numlines
        else:
            raise RcsError("This shouldn't be possible")

    return "\n".join(source)


def SymNumStringToList(s):
    r = re.compile("^\s*(?:([0-9]*[a-z][0-9a-z]*):([0-9.]+))\s+(.*)$")
    ret = []
    m = re.search(r, s)
    while m != None:
        ret += (m[0], m[1])
        s = m[2]
        m = re.search(r, s)
    return ret


def textOrNone(phrase, value, semicolon = True):
    """If the value is None then return the empty string, otherwise return
    a string containing phrase followed by value and (if semicolon is
    True) a semicolon."""
    if value == None:
        return ""
    elif semicolon:
        return "%s %s;\n"%(phrase, value)
    else:
        return "%s %s\n"%(phrase, value)


class RcsError(Exception):
    """Class for errors produced by EditRCS"""

    def __init__(self, value):
        """Return an RcsError object with the given error string set to
        value."""
        self.value = value

    def __str__(self):
        """Return this object's error string."""
        return repr(self.value)


############################################################################
# Lexer class
############################################################################
class Lexer:
    """Lexer class used by ParseRcs() and other utility functions."""

    # Lexer remembers the current position
    def __init__(self, text):
        """Return a lexer object initialised with the given string."""
        self.text = text
        self.textlen = len(text)
        self.offset = 0
        self.whitespace = " \b\t\n\v\f\r"
        self.special = "$,.:;@"
        idchars = ""
        for i in range(0, 255):
             if 0x21 <= i <= 0x7E or 0xA0 <= i <= 0xFF:
                 c = chr(i)
                 if c not in self.special:
                     idchars += chr(i)
        self.idchar_re = "[%s]"%idchars

    def error(self, text):
        """Raise an RcsError with text and the current offset as context"""
        raise RcsError("Syntax error: %s at offset %d"%(text, self.offset))

    def expectedError(self, text):
        """Raise an RcsError saying text was expected and the current offset
        as context."""
        self.error("expected %s"%text)

    def getRE(self, regexp, must_have, err_tok):
        """Try to parse the regular expression regexp.  If it can't and 
        must_have is True, then raise an error saying err_tok was expected.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        #print("%s -> %s"%(regexp, self.text[self.offset:]))
        skip_whitespace = "([%s]*)"%self.whitespace
        res = re.search("^" + skip_whitespace + regexp,
                        self.text[self.offset:],
                        re.DOTALL)
        if res == None:
            if must_have:
                self.expectedError("'%s'"%err_tok)
            tok = None
        else:
            (ws, tok,) = res.groups()
            self.offset += len(ws) + len(tok)
        #print("%s -> %d"%(tok, self.offset))
        return tok

    def getNum(self, must_have = True):
        """Try to get an RCS num.  Error if it can't and must_have is True.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        return self.getRE('([0-9.]+)', must_have, "<num>")

    def getSym(self, must_have = True):
        """Try to get an RCS sym.  Error if it can't and must_have is True.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        # In the grammar, "sym ::= {digit}* idchar {idchar|digit}".  I don't
        # see the difference between that and "sym ::= {idchar}*" - perhaps I'm
        # missing something but "rcs -a2 foo" works.
        # ... In fact the 5.9.2 version of the manpage has exactly that!
        return self.getRE('(%s+)'%self.idchar_re, must_have, "<sym>")

    def getId(self, must_have = True):
        """Try to get an RCS id.  Error if it can't and must_have is True.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        # In the grammar, "id ::= {num} idchar {idchar|num}*".  I don't see
        # the difference between that and "id ::= {.|idchar}*" - perhaps I'm
        # missing something but "rcs -n5:1.1 foo" works.
        # ... In fact the 5.9.2 version of the manpage has exactly that!
        return self.getRE('((?:\.|%s)+)'%self.idchar_re, must_have, "<id>")

    def getKw(self, kw, must_have = True):
        """Try to get the given RCS keyword.  Error if it can't and must_have
        is True.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        return self.getRE('(%s)(?:[%s%s]|$)'%(kw,
                                              self.whitespace,
                                              self.special),
                          must_have,
                          "'%s'"%kw)

    def getString(self, must_have = True):
        """Try to get an RCS at-quoted string.  Error if it can't and must_have
        is True.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        return self.getRE('(@(?:[^@]|@@)*@)(?:[^@]|$)', must_have, "<string>")

    def getSemicolon(self, must_have = True):
        """Try to get a semi-colon.  Error if it can't and must_have is
        True.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        return self.getRE('(;)', must_have, "';'")

    def getColon(self, must_have = True):
        """Try to get a colon.  Error if it can't and must_have is True.
        Return the matching token as a string if it succeeded and None if
        it failed and must_have is False."""
        return self.getRE('(:)', must_have, "':'")

    def checkNewlineTerm(self):
        """Try to get a newline and end-of-string, as required by the RCS file
        format.  Error if it can't."""
        self.getRE('(\n)$',
                   True,
                   "file to end with a newline ('\\n') character");


############################################################################
# RcsDelta class
############################################################################
class RcsDelta:
    """Class representing the structure of a delta in an RCS file"""

    def __init__(self, revision):
        """Return an uninitialised RcsDelta object.  The caller is responsible
        for filling in the fields."""
        self.__revision = revision
        self.__commitid = None
        self.__date = None
        self.__author = None
        self.__state = None
        self.__branches = None
        self.__next = None
        self.__log = None
        self.__text = None
        self.__text_is_diff = None

    def setRevision(self, value):
        """Set the revision number for this delta.  This is an RCS dotted
        number with an even number of components.
        See the rcsfile(5) manpage for how revision numbers are used.  EditRCS
        doesn't (currently) enforce this but different numbering schemes will
        probably break other tools."""
        self.__revision = value

    def getRevision(self):
        """Get the revision number for this delta.  This is an RCS dotted
        number with an even number of components.
        See the rcsfile(5) manpage for how revision numbers are used.  EditRCS
        doesn't (currently) enforce this but different numbering schemes will
        probably break other tools."""
        return self.__revision

    def setCommitId(self, value):
        """Get the commitid field, a value unique in the RCS file used to
        identify a commit operation applied to a set of RCS files."""
        self.__commitid = value
        
    def getCommitId(self):
        """Get the commitid field, a value unique in the RCS file used to
        identify a commit operation applied to a set of RCS files."""
        return self.__commitid

    def setDate(self, value):
        """Set the date field, giving the date and time at which this delta
        was checked in."""
        self.__date = value

    def getDate(self):
        """Get the date field, giving the date and time at which this delta
        was checked in."""
        return self.__date

    def setAuthor(self, value):
        """Set the author field, giving the identity of the user who checked
        in this delta."""
        self.__author = value

    def getAuthor(self):
        """Get the author field, giving the identity of the user who checked
        in this delta."""
        return self.__author

    def setState(self, value):
        """Set the state field.  RCS defaults this to Exp ("experimental") but
        it can be changed to a user-defined value such as "stable" or 
        "released".  CVS sets it to "dead" for deleted files."""
        if value == None:
            value = ""
        self.__state = value

    def getState(self):
        """Get the state field.  RCS defaults this to Exp ("experimental") but
        it can be changed to a user-defined value such as "stable" or 
        "released".  CVS sets it to "dead" for deleted files."""
        return self.__state

    def setBranches(self, value, from_list = True):
        """Set the branches field.  This is a list of the first nodes of
        all branches from this delta."""
        if value == None:
            value = ""
        elif from_list:
            self.__branches = ListToStringNums(value)
        else:
            self.__branches = value

    def getBranches(self, to_list = True):
        """Get the branches field.  This is a list of the first nodes of
        all branches from this delta."""
        if to_list:
            return StringNumsToList(self.__branches)
        else:
            return self.__branches

    def setNext(self, value):
        """Set the next field, pointing to the next revision.  For the trunk
        this is a *previous* revision but for branches it is a *subsequent*
        revision.  See the diagram in the rcsfile(5) manpage."""
        if value == None:
            value = ""
        self.__next = value

    def getNext(self):
        """Get the next field, pointing to the next revision.  For the trunk
        this is a *previous* revision but for branches it is a *subsequent*
        revision.  See the diagram in the rcsfile(5) manpage."""
        return self.__next

    def setLog(self, value, handle_quoting = True):
        """Set the log field given by the user for this revision.
        If handle_quoting then RCS at quoting is to be added, otherwise value
        is assumed to have been quoted already."""
        if handle_quoting:
            self.__log = AddAtQuoting(value)
        else:
            self.__log = value

    def getLog(self, handle_quoting = True):
        """Set the log field given by the user for this revision.  If
        handle_quoting then the RCS at quoting will be removed."""
        if handle_quoting:
            return RemoveAtQuoting(self.__log)
        else:
            return self.__log

    def setText(self, value, text_is_diff, handle_quoting = True):
        """Set the text field to value.  If text_is_diff then it is to be
        regarded as a diff, otherwise it is to be regarded as a revision.
        (In an RCS file the head should be a revision and the other deltas
        are diffs.)
        If handle_quoting then RCS at quoting is to be added, otherwise value
        is assumed to have been quoted already."""
        self.__text_is_diff = text_is_diff
        if handle_quoting:
            self.__text = AddAtQuoting(value)
        else:
            self.__text = value

    def getTextIsDiff(self):
        """Return True if the text field is currently a diff or False 
        otherwise (a revision)."""
        return self.__text_is_diff

    def getText(self, handle_quoting = True):
        """Return the text field.  If handle_quoting then the RCS at quoting
        will be removed."""
        if handle_quoting:
            return RemoveAtQuoting(self.__text)
        else:
            return self.__text

    def textToDiff(self, prev_rev):
        """If the text field is currently a revision then, using prev_rev as
        the previous revision, set the text field to the resulting diff.
        Otherwise, raise a RcsError."""
        if self.__text_is_diff:
            raise RcsError("revision %s is already a diff!"%self.__revision)
        if prev_rev.getTextIsDiff():
            raise RcsError("previous revision %s is a diff!"%prev_rev.getRevision())
        self.setText(TextToDiff(prev_rev.getText(),
                                self.getText()),
                     True)

    def textFromDiff(self, prev_rev):
        """If the text field is currently a diff then, using prev_rev as the
        previous revision, set the text field to the resulting revision.
        Otherwise, raise a RcsError."""
        if not self.__text_is_diff:
            raise RcsError("revision %s is not a diff!"%self.__revision)
        self.setText(TextFromDiff(prev_rev.getText(),
                                  self.getText()),
                     False)

    def validate(self):
        """Validate the RcsDelta object for missing phrases and other
        problems.  If a problem is found then raise an RcsError."""
        # This implicitly checks that there is a delta and a delta text for
        # every revision.
        if self.getDate() == None:
            raise RcsError("date is not set (and is not optional)")
        if self.getAuthor() == None:
            raise RcsError("author is not set (and is not optional)")
        if self.getState() == None:
            raise RcsError("state is not set (and is not optional)")
        if self.getBranches() == None:
            raise RcsError("branches is not set (and is not optional)")
        if self.getNext() == None:
            raise RcsError("next is not set (and is not optional)")
        if self.getLog() == None:
            raise RcsError("log is not set (and is not optional)")
        if self.getText() == None:
            raise RcsError("text is not set (and is not optional)")

    def deltaToString(self):
        """Return a string representation of the "delta" part of the RCS 
        grammar for this RcsDelta object.  This assumes that validate() has
        already been checked in the containing Rcs object."""
        s = ("%s\n"%self.__revision
             + textOrNone("date", self.__date)
             + textOrNone("author", self.__author)
             + textOrNone("state", self.__state)
             + textOrNone("branches", self.__branches)
             + textOrNone("next", self.__next)
             + textOrNone("commitid", self.__commitid)
             + "\n")
        return s

    def deltaTextToString(self):
        """Return a string representation of the "deltatext" part of the RCS 
        grammar for this RcsDelta object.  This assumes that validate() has
        already been checked in the containing Rcs object."""
        # This assumes that Rcs.validate() has been checked
        s = ("%s\n"%self.__revision
             + textOrNone("log", self.__log, False)
             + textOrNone("text", self.__text, False)
             + "\n")
        return s
        

############################################################################
# Rcs class
############################################################################
class Rcs:
    """Class representing the structure of an RCS file"""

    def __init__(self):
        """Return an uninitialised Rcs object.  The caller is responsible for
        filling in the fields."""
        # These are stored as strings as they appear in the rcs file.  The 
        # getters and setters do conversion and validation.
        self.__deltas = []
        self.__head = None
        self.__branch = None
        self.__access = None
        self.__symbols = None
        self.__locks = None
        self.__strict = None
        self.__integrity = None
        self.__comment = None
        self.__expand = None
        self.__desc = None

        self.revisionsAreDiffs = True

    def setHead(self, revision):
        """Set the head revision.  This is the RCS dotted number of the latest
        revision on the trunk."""
        if revision == None:
            revision = ""
        self.__head = revision
        
    def getHead(self):
        """Get the head revision.  This is the RCS dotted number of the latest
        revision on the trunk."""
        return self.__head

    def setBranch(self, revision):
        """Set the default branch (or revision) for RCS operations."""
        if revision == None:
            revision = ""
        self.__branch = revision
        
    def getBranch(self):
        """Get the default branch (or revision) for RCS operations."""
        return self.__branch

    def setAccess(self, value):
        """Set the access field.  This is a whitespace-separated list of ids
        for the users who are allowed to modify the RCS file.  If it is empty
        then any user can modify the file."""
        if value == None:
            value = ""
        self.__access = value
        
    def getAccess(self):
        """Get the access field.  This is a whitespace-separated list of ids
        for the users who are allowed to modify the RCS file.  If it is empty
        then any user can modify the file."""
        return self.__access

    def setSymbols(self, value, from_map = True):
        """Set the symbols field.  This is a whitespace-separated list of
        mappings from symbolic names to RCS dotted revision numbers (of the 
        form <sym>:<num>).  The symbolic names can be used as tags, possibly
        across multiple RCS files."""
        if value == None:
            value = ""
        elif from_map:
            self.__symbols = MapToStringColonMap(value)
        else:
            self.__symbols = value
        
    def getSymbols(self, to_map = True):
        """Get the symbols field.  This is a whitespace-separated list of
        mappings from symbolic names to RCS dotted revision numbers (of the 
        form <sym>:<num>).  The symbolic names can be used as tags, possibly
        across multiple RCS files."""
        if to_map:
            return StringColonMapToMap(self.__symbols)   
        else:
            return self.__symbols

    def setLocks(self, value, from_map = True):
        """Set the locks field.  This is a whitespace-separated list of
        mappings from user ids to RCS dotted revision numbers (of the form
        <id>:<num>).  This is used to identify which revisions have been locked
        by users."""
        if value == None:
            value = ""
        elif from_map:
            self.__locks = MapToStringColonMap(value)
        else:
            self.__locks = value
        
    def getLocks(self, to_map = True):
        """Get the locks field.  This is a whitespace-separated list of
        mappings from user ids to RCS dotted revision numbers (of the form
        <id>:<num>).  This is used to identify which revisions have been locked
        by users."""
        if to_map:
            return StringColonMapToMap(self.__locks)
        else:
            return self.__locks

    def setStrict(self, value, from_bool = True):
        """Set the strict field.  If set then RCS requires a user to hold 
        a lock on a revision before being allowed to check in the next
        revision.
        This function expects value to be a boolean (unless from_bool is
        False)."""
        if from_bool:
            if value:
                value = ""
            else:
                value = None
        else:
            if value not in [None, ""]:
                raise RcsError("struct can only be None or \"\"")
        self.__strict = value
        
    def getStrict(self, to_bool = True):
        """Get the strict field.  If set then RCS requires a user to hold 
        a lock on a revision before being allowed to check in the next
        revision.
        This function expects value to be a boolean (unless from_bool is
        False)."""
        if to_bool:
            if value not in [None, ""]:
                raise RcsError("struct can only be None or \"\"")
            return self.__strict == ""
        else:
            return self.__strict

    def setIntegrity(self, value, handle_quoting = True):
        """Set the integrity field.  This was added in RCS 5.8 for RCS and
        implementation-defined extensions.
        If handle_quoting then RCS at quoting is to be added, otherwise value
        is assumed to have been quoted already."""
        if handle_quoting:
            self.__integrity = AddAtQuoting(value)
        else:
            self.__integrity = value
        
    def getIntegrity(self, handle_quoting = True):
        """Get the integrity field.  This was added in RCS 5.8 for RCS and
        implementation-defined extensions.
        If handle_quoting then the RCS at quoting will be removed."""
        if handle_quoting:
            return RemoveAtQuoting(self.__integrity)
        else:
            return self.__integrity

    def setComment(self, value, handle_quoting = True):
        """Set the comment field.  This is an obsolete option used by old
        RCS versions for $Log$.
        If handle_quoting then RCS at quoting is to be added, otherwise value
        is assumed to have been quoted already."""
        if handle_quoting:
            self.__comment = AddAtQuoting(value)
        else:
            self.__comment = value
        
    def getComment(self, handle_quoting = True):
        """Set the comment field.  This is an obsolete option used by old
        RCS versions for $Log$.
        If handle_quoting then the RCS at quoting will be removed."""
        if handle_quoting:
            return RemoveAtQuoting(self.__comment)
        else:
            return self.__comment

    def setExpand(self, value, handle_quoting = True):
        """Set the expand field.
        If handle_quoting then RCS at quoting is to be added, otherwise value
        is assumed to have been quoted already."""
        if handle_quoting:
            self.__expand = AddAtQuoting(value)
        else:
            self.__expand = value
        
    def getExpand(self, handle_quoting = True):
        """Get the expand field.
        If handle_quoting then the RCS at quoting will be removed."""
        if handle_quoting:
            return RemoveAtQuoting(self.__expand)
        else:
            return self.__expand

    def addDelta(self, revision, delta):
        """Add the given delta as the given revision number."""
        for d in self.__deltas:
            if d.getRevision() == revision:
                raise RcsError("Revision %s already in deltas"%(revision))
        self.__deltas.append(delta)

    def getDelta(self, revision):
        """Return the delta for the given revision number."""
        for d in self.__deltas:
            if d.getRevision() == revision:
                return d
        raise RcsError("Revision %s not found in deltas"%(revision))

    def delDelta(self, revision):
        """Delete the delta for the given revision number."""
        for d in self.__deltas:
            if d.getRevision() == revision:
                del self.__deltas[self.__deltas.index(d)]
        raise RcsError("Revision %s not found in deltas"%(revision))

    def mapDeltas(self, apply_fn):
        """Apply the function apply_fn() to each delta in turn."""
        for d in self.__deltas:
            apply_fn(d)

    def setDesc(self, value, handle_quoting = True):
        """Set the description field given by the user for this RCS file.
        If handle_quoting then RCS at quoting is to be added, otherwise value
        is assumed to have been quoted already."""
        if handle_quoting:
            self.__desc = AddAtQuoting(value)
        else:
            self.__desc = value
        
    def getDesc(self, handle_quoting = True):
        """Get the description field given by the user for this RCS file.
        If handle_quoting then the RCS at quoting will be removed."""
        if handle_quoting:
            return RemoveAtQuoting(self.__desc)
        else:
            return self.__desc
        
    def validate(self):
        """Validate the Rcs object for missing phrases and other problems.
        If a problem is found then raise an RcsError."""
        for d in self.__deltas:
            d.validate()
            # TODO Check that d's next is in self.__deltas
            # TODO Check that head, branch, etc. are in self.__deltas

        if self.getHead() == None:
            raise RcsError("head is not set (and is not optional)")
        if self.getAccess() == None:
            raise RcsError("access is not set (and is not optional)")
        if self.getSymbols(False) == None:
            raise RcsError("symbols is not set (and is not optional)")
        if self.getLocks(False) == None:
            raise RcsError("locks is not set (and is not optional)")
        if self.getDesc() == None:
            raise RcsError("desc is not set (and is not optional)")

    def toString(self):
        """Return a string representation of the RCS file for this object.
        This performs validation using validate()."""
        self.validate()

        s = (textOrNone("head", self.__head)
             + textOrNone("branch", self.__branch)
             + textOrNone("access", self.__access)
             + textOrNone("symbols", self.__symbols)
             + textOrNone("locks", self.__locks)
             + textOrNone("strict", self.__strict)
             + textOrNone("comment", self.__comment)
             + textOrNone("expand", self.__expand)
             + "\n"
             + "".join(map(lambda d: d.deltaToString(), self.__deltas))
             + textOrNone("desc", self.__desc, False)
             + "\n"
             + "".join(map(lambda d: d.deltaTextToString(), self.__deltas)))
        return s


############################################################################
# ParseRcs function
############################################################################
def ParseRcs(text):
    """Parse a string in RCS format and return a corresponding Rcs object"""

    # RCS file format is a regular expression!

    rcs = Rcs()
    lex = Lexer(text)

    lex.getKw("head")
    rcs.setHead(lex.getNum())
    lex.getSemicolon()

    if lex.getKw("branch", False) != None:
        rcs.setBranch(lex.getNum())
        lex.getSemicolon()

    t = lex.getKw("access")
    access_list = []
    while True:
        t = lex.getId(False)
        if t == None:
            break
        access_list.append(t)
    rcs.setAccess(" ".join(access_list))
    lex.getSemicolon()

    lex.getKw("symbols")
    symbols_list = []
    while True:
        t1 = lex.getSym(False)
        if t1 == None:
            break
        lex.getColon()
        t2 = lex.getNum()
        symbols_list.append("%s:%s"%(t1, t2))
    rcs.setSymbols(" ".join(symbols_list), False)
    lex.getSemicolon()

    lex.getKw("locks")
    locks_list = []
    while True:
        t1 = lex.getId(False)
        if t1 == None:
            break
        lex.getColon()
        t2 = lex.getNum()
        locks_list.append("%s:%s"%(t1, t2))
    rcs.setLocks(" ".join(locks_list), False)
    lex.getSemicolon()

    if lex.getKw("strict", False) != None:
        rcs.setStrict("", False)
        lex.getSemicolon()

    if lex.getKw("integrity", False) != None:
        rcs.setIntegrity(lex.getString(False), False)
        lex.getSemicolon()

    if lex.getKw("comment", False) != None:
        rcs.setComment(lex.getString(False), False)
        lex.getSemicolon()

    if lex.getKw("expand", False) != None:
        rcs.setExpand(lex.getString(False), False)
        lex.getSemicolon()

    # Haven't implemented <newphrase> from rcs 5.6, which would go here.

    # We might need a better parser (or at least backtracking) because 
    # <newphrase> is ';' terminated and we can't otherwise distinguish the 
    # keywords from <num> in <delta>.
    # But actually rcs 5.7 source code assumes that if a token contains an
    # idchar that isn't a digit or a special then it's an ID; and it doesn't
    # distinguish between SYM and ID.

    while True:
        rev = lex.getNum(False)
        if rev == None:
            break

        delta = RcsDelta(rev)
        rcs.addDelta(rev, delta)

        lex.getKw("date")
        delta.setDate(lex.getNum())
        lex.getSemicolon()

        lex.getKw("author")
        delta.setAuthor(lex.getId())
        lex.getSemicolon()

        lex.getKw("state")
        delta.setState(lex.getId(False))
        lex.getSemicolon()

        lex.getKw("branches")
        branches_list = []
        while True:
            t = lex.getNum(False)
            if t == None:
                break
            branches_list.append(t)
        delta.setBranches(" ".join(branches_list))
        lex.getSemicolon()

        lex.getKw("next")
        delta.setNext(lex.getNum(False))
        lex.getSemicolon()

        if lex.getKw("commitid", False) != None:
            delta.setCommitId(lex.getId(True))
            lex.getSemicolon()

        # Haven't implemented <newphrase> from rcs 5.6, which would go here.

    lex.getKw("desc")
    rcs.setDesc(lex.getString(), False)

    while True:
        rev = lex.getNum(False)
        if rev == None:
            break

        delta = rcs.getDelta(rev)

        lex.getKw("log")
        delta.setLog(lex.getString(), False)

        lex.getKw("text")
        delta.setText(lex.getString(), (rcs.getHead() != rev), False)

    lex.checkNewlineTerm()
    return rcs

############################################################################
