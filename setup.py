from setuptools import setup, find_packages
from setuptools.command.install import install
from shutil import copyfile
import os
import subprocess

#Read requirements.txt
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
        
        try:
            if not os.path.exists('/usr/local/share/applications'):
                os.makedirs('/usr/local/share/applications')
            copyfile('dosview.desktop', '/usr/local/share/applications/dosview.desktop')
            
            if not os.path.exists('/usr/local/share/icons'):
                os.makedirs('/usr/local/share/icons')
            copyfile('media/icon_ust.png', '/usr/local/share/icons/icon_ust.png')
        except Exception as e:
            print(f"Error: {e}")
            print("Dosview intsallation script failed .. ")
# Get the commit hash
#commit_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()

version_ns = {}
with open("dosview/version.py") as f:
    exec(f.read(), version_ns)

setup(
    name='dosview',
    version=version_ns["__version__"],
    description='Dosview is a simple graphical log viewer and control interface for Universial Scientific Technologies (UST) dosimeters.', 
    long_description=long_description,
    long_description_content_type='text/markdown',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'dosview = dosview:main',
        ],
    },
    include_package_data=True,
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
