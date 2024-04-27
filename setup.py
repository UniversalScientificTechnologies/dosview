from setuptools import setup, find_packages
from setuptools.command.install import install
from shutil import copyfile
import os
import subprocess

# Read requirements.txt
with open('requirements.txt') as f:
    required = f.read().splitlines()

# Read README.md for the long description
with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

class PostInstallCommand(install):
    """Post-installation for installation mode."""
    def run(self):
        print("Dosview intsallation script in progress .. ")

        install.run(self)
        
        if not os.path.exists('/usr/local/share/applications'):
            os.makedirs('/usr/local/share/applications')
        copyfile('dosview.desktop', '/usr/local/share/applications/dosview.desktop')
        
        if not os.path.exists('/usr/local/share/icons'):
            os.makedirs('/usr/local/share/icons')
        copyfile('media/icon_ust.png', '/usr/local/share/icons/icon_ust.png')

# Get the commit hash
#commit_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()

setup(
    name='dosview',
    version=f'0.1.10',
    description='A .dos file viewer', 
    long_description=long_description,
    long_description_content_type='text/markdown',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'dosview = dosview:main',
        ],
    },
    install_requires=required,
    cmdclass={
        'install': PostInstallCommand,
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
)
