import csv
from datetime import date
import logging
from pathlib import Path
import shutil
from typing import Optional
from xml.etree.ElementTree import Element, ElementTree, SubElement
from zipfile import ZipFile, ZIP_DEFLATED

import pydantic

DEFAULT_ENCODING = "utf-8"


logger = logging.getLogger(__name__)


class DublinCoreDate(pydantic.BaseModel):
    issued: date


class DublinCoreElement(pydantic.BaseModel):
    element: str
    value: str
    qualifier: Optional[str] = None
    language: Optional[str] = None


class DublinCore(pydantic.BaseModel):
    elements: list[DublinCoreElement]


def build_xml(dc: DublinCore) -> ElementTree:
    root = Element("dublin_core")
    for element in dc.elements:
        dcvalue(
            root,
            element=element.element,
            qualifier=element.qualifier,
            language=element.language,
            text=element.value,
        )
    return ElementTree(root)


def dcvalue(
    parent: Element,
    element: str,
    qualifier: Optional[str] = None,
    language: Optional[str] = None,
    text: Optional[str] = None,
) -> Element:
    attribs = {
        "element": element,
        "qualifier": qualifier or "none",
    }
    if language:
        attribs["language"] = language
    elem = SubElement(parent, "dcvalue", attrib=attribs)
    if text:
        elem.text = text
    return elem


class Item(pydantic.BaseModel):
    files: list[Path]
    dc: DublinCore

    @pydantic.validator("files", pre=True)
    def split_str(cls, v):
        return v.split("||") if isinstance(v, str) else v

    @pydantic.root_validator(pre=True)
    def collect_dc_fields(cls, values):
        new_values = {}
        for field, value in values.items():
            if field.startswith("dc."):
                if "dc" not in new_values:
                    new_values["dc"] = {}
                if "elements" not in new_values["dc"]:
                    new_values["dc"]["elements"] = []
                subfields = field.split(".")
                element = {"value": value}
                for sub_field, key in zip(
                    subfields[1:], ("element", "qualifier", "language"), strict=False
                ):
                    element[key] = sub_field
                new_values["dc"]["elements"].append(element)
                # new_values["dc"][field[3:]] = value
            else:
                new_values[field] = value
        return new_values


class SimpleArchive:
    def __init__(self, input_folder: Path, items: list) -> None:
        self.input_folder = input_folder
        self.items = items

    @classmethod
    def from_csv_path(cls, csv_path: Path) -> "SimpleArchive":
        items = []
        with open(csv_path, encoding=DEFAULT_ENCODING, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                item = Item(**row)
                items.append(item)
        return cls(input_folder=csv_path.parent, items=items)

    def write_to_path(self, output_path: Path) -> None:
        for item_nr, item in enumerate(self.items):
            item_path = output_path / f"item_{item_nr:03d}"
            logger.info("creating '%s' ...", item_path)
            item_path.mkdir(parents=True, exist_ok=False)

            self.write_contents_file(item, item_path)
            self.copy_files(item, item_path)
            self.write_metadata(item, item_path)

    def write_to_zip(self, output_path: Path) -> None:
        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zipfile:
            for item_nr, item in enumerate(self.items):
                item_path = f"item_{item_nr:03d}"
                # zipfile.mkdir(item_path)
                # copy files
                for file_path in item.files:
                    src_path = self.input_folder / file_path
                    dst_path = f"{item_path}/{file_path}"
                    zipfile.write(src_path, dst_path)
                # write contents
                contents_path = f"{item_path}/contents"
                with zipfile.open(contents_path, "w") as contents_file:
                    for file_path in item.files:
                        contents_file.write(file_path.name.encode("utf-8"))
                        contents_file.write(b"\n")
                # write metadata
                dublin_core_xml = build_xml(item.dc)
                dublin_core_path = f"{item_path}/dublin_core.xml"
                logger.info("writing '%s'in zip-archive ", dublin_core_path)
                with zipfile.open(dublin_core_path, "w") as dublin_core_file:
                    dublin_core_xml.write(dublin_core_file)

    def write_contents_file(self, item: Item, item_path: Path) -> None:
        contents_path = item_path / "contents"
        logger.info("writing '%s'", contents_path)
        with contents_path.open(mode="w", encoding="utf-8") as contents_file:
            for file_path in item.files:
                contents_file.write(file_path.name)
                contents_file.write("\n")

    def copy_files(self, item: Item, item_path: Path) -> None:
        for file_path in item.files:
            src_path = self.input_folder / file_path
            dst_path = item_path
            logger.info("  copying '%s to '%s'", src_path, dst_path)
            shutil.copy(src_path, dst_path)

    def write_metadata(self, item: Item, item_path: Path) -> None:
        dublin_core_xml = build_xml(item.dc)
        dublin_core_path = item_path / "dublin_core.xml"
        logger.info("writing '%s'", dublin_core_path)
        dublin_core_xml.write(dublin_core_path)
