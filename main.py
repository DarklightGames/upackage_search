import argparse
import json
import os
import re
from concurrent.futures import as_completed, ThreadPoolExecutor
from humanize.filesize import naturalsize
from subprocess import Popen, PIPE
from tqdm import tqdm

regex = re.compile(r"^\s+\d+\s+([A-F0-9]+)\s+([A-F0-9]+)\s+(\w+)\s+(.+)$", flags=re.MULTILINE)
valid_extensions = ['.utx', '.ukx', '.usx', '.uax']


class Package(object):
    def __init__(self, name):
        self.name = name
        self.records = dict()


class Record(object):
    def __init__(self, package: Package, name: str, type_: str, size: int):
        self.package = package
        self.name = name
        self.type_ = type_
        self.size = size

    @property
    def identifier(self):
        return f'{self.type_}\'{self.package.name}.{self.name}\''


def umodel_list_package(umodel_path: str, path: str) -> Package:
    package = Package(name=os.path.splitext(os.path.basename(path))[0])
    args = [umodel_path, '-list', path]
    excluded_types = [
        'Package',  # "package" types are for groups, maybe a data-block within the asset itself?
        'ConstantColor',
        'VertexColor'
    ]
    with Popen(args, stdout=PIPE, stderr=None, shell=True) as process:
        output = process.communicate()[0].decode('windows-1252')
        output = output.replace('\r', '')
        for offset, size, type_, name in regex.findall(output):
            if type_ in excluded_types:
                continue
            size = int(size, 16)
            record = Record(package, name, type_, size)
            package.records[record.name] = record
    return package


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root_path', type=str)
    args = parser.parse_args()

    root_path = None

    # load the configuration file
    config = {
        'umodel_path': None,
        'root_path': None
    }

    try:
        with open('./config.json', 'r') as fp:
            data = json.load(fp)
            config['umodel_path'] = data.get('umodel_path', None)
            config['root_path'] = data.get('root_path', None)
    except IOError:
        print('Config not found, let\'s create it!')
        while True:
            umodel_path = input('Enter the path to the umodel executable:').upper()
            if os.path.exists(umodel_path):
                process = Popen([umodel_path, '-version'], stdout=PIPE, stderr=None, shell=True)
                output = process.communicate()[0].decode('windows-1252')
                output = output.replace('\r', '')
                if process.returncode == 0 and 'https://www.gildor.org/en/projects/umodel' in output:
                    config['umodel_path'] = umodel_path
                print('umodel_path is good!')
                break
            else:
                print('Path doesn\'t exist, try again')
        while True:
            root_path = input('Enter the root directory (eg. the root Red Orchestra directory)')
            if os.path.exists(root_path) and os.path.isdir(root_path):
                config['root_path'] = root_path
                break
            else:
                print('Invalid root directory, try again!')
                continue
        # write the directory out
        with open('./config.json', 'w') as fp:
            json.dump(config, fp)

    if 'root_path' in args and args.root_path is not None:
        root_path = args.root_path
    else:
        root_path = config['root_path']

    umodel_path = config['umodel_path']

    # build a list of all the package paths we want to scan
    package_paths = []
    for root, dirs, files in os.walk(root_path):
        for file in filter(lambda x: os.path.splitext(x)[1] in valid_extensions, files):
            package_paths.append(os.path.join(root, file))
    print(f'Indexing {len(package_paths)} package file(s)\n')
    with tqdm(total=len(package_paths)) as progress_bar:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(umodel_list_package, umodel_path, path): path for path in package_paths}
            results = {}
            for future in as_completed(futures):
                arg = futures[future]
                results[arg] = future.result()
                progress_bar.set_description_str(os.path.basename(arg))
                progress_bar.update(1)
    print(f'Indexing complete!')
    while True:
        # prompt the user for a search term
        search_text = input('>').upper()
        if len(search_text) == 0:
            continue
        paths = []
        for package in results.values():
            for key, record in package.records.items():
                if search_text in key.upper():
                    print(f'{record.identifier}: {naturalsize(record.size)}')
