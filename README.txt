EditRCS is a library to with functions to read RCS files into Python
classes Rcs and RcsDelta, and to manipulate them and write them to a new
RCS file.

It is intended to be used to manipulate RCS files in ways that the RCS tools
don't support, but it requires some knowledge of how RCS files work rather
than being a polished command-line tool.

See rcsfile(5) for RCS file format definition.

Example scripts in the examples directory include:

checkout_start: print the earliest version of a RCS file to standard output.
rcs_join: produce an RCS file with the history of one file followed by that of 
          a second file.
rename_user: replace an old user name with a new one for each revision checked
             in by that user.
pivot_branch: given a branch head and a first-level branch head off that, swap
              the sub-branch and the main branch.

Limitations: I'm going with the 5.9.2 version of the manpage, and ignoring 
the newphrase in the earlier (e.g. 5.6) specifications for now.
It is written to be simple rather than optimised for speed or space.


INSTALLATION
------------

To install as a Python module run this as root:

    python setup.py install
