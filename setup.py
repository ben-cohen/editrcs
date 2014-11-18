from distutils.core import setup

setup(
    name='editrcs',
    version='0.5.0',
    author='Ben Cohen',
    packages=['editrcs'],
    url='http://github.com/ben-cohen/editrcs',
    license='GPLv3+',
    description='Library to read, manipulate and write RCS files.',
    long_description=open('README.txt').read(),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Natural Language :: English',
        'Operating System :: POSIX',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Unix',
        'Programming Language :: Python',
        'Topic :: Software Development :: Version Control :: CVS',
        'Topic :: Software Development :: Version Control :: RCS']
)
