import argparse
import zipfile
from bs4 import BeautifulSoup
import os
import shutil
from PIL import Image, ImageChops
import cssutils
from pathlib import Path
import configparser
import sys
import traceback
import logging
logger = logging.getLogger(__name__)

def get_app_config_dir():
    xdg_config_home_env = os.environ.get('XDG_CONFIG_HOME')
    if xdg_config_home_env:
        config_home = Path(xdg_config_home_env)
    else:
        config_home = Path.home() / ".config"
    return config_home / "epub-optimizer"

def trim_image(img):
    background_color = (255, 255, 255)
    # Open the image

    # Convert the image to RGB (in case it's not)
    img = img.convert("RGB")

    # Create a background image with the same size as the input image
    bg = Image.new(img.mode, img.size, background_color)

    # Calculate the difference and the bounding box
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()

    cropped_img = img
    # If there's a bounding box, crop the image
    if bbox:
        cropped_img = img.crop(bbox)
        logger.debug(f"Image cropped")
    else:
        logger.debug("No content to trim.")
    return cropped_img


def modify_img_tags(epub_path, output_path, width, height):
    desired_resolution = (width, height)
    desired_width, desired_height = desired_resolution
    aspect_ratio = desired_height / desired_width

    # Temporary directory for extracting EPUB contents
    temp_dir = "/tmp/temp_epub"

    # Ensure the output directory is clean
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    # Extract EPUB contents
    with zipfile.ZipFile(epub_path, "r") as epub:
        epub.extractall(temp_dir)

    cssParser = cssutils.CSSParser(validate=False)

    # Locate and process HTML/XHTML files
    try:
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(".css"):
                    file_path = os.path.join(root, file)

                    # Read and parse the HTML file
                    sheet = cssParser.parseFile(file_path)
                    for rule in list(sheet.cssRules):
                        if (
                            rule.type == rule.STYLE_RULE
                            and rule.selectorText == "div.IMG---Figure"
                        ):
                            rule.style.setProperty("page-break-after", "always")
                        else:
                            if (
                                rule.type == rule.STYLE_RULE
                                and rule.selectorText == "img"
                            ):
                                sheet.deleteRule(rule)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(sheet.cssText.decode("utf-8"))
                if file.endswith(".html") or file.endswith(".xhtml"):
                    file_path = os.path.join(root, file)

                    # Read and parse the HTML file
                    with open(file_path, "r", encoding="utf-8") as f:
                        soup = BeautifulSoup(f, "html.parser")
                    # Modify <img> tags to ensure full-screen resolution
                    for img in soup.find_all("img"):
                        style = "width: 100vw; height: 100vh; object-fit: cover;"
                        if "src" in img.attrs:
                            img_path = os.path.join(root, img["src"])
                            if img["src"][-4:] != ".svg" and os.path.exists(img_path):
                                with Image.open(img_path) as image:
                                    # Cropping
                                    image = trim_image(image)
                                    width, height = image.size
                                    # Rotation
                                    if width > height:
                                        image = image.rotate(90, expand=True)
                                        tmp = height
                                        height = width
                                        width = tmp
                                    # Magnification
                                    magnify_factor = (
                                        desired_height / height
                                        if height / width > aspect_ratio
                                        else desired_width / width
                                    )
                                    image = image.resize(
                                            (
                                                round(width * magnify_factor),
                                                round(height * magnify_factor),
                                            )
                                        )
                                    image.save(img_path)
                        img["style"] = style
                    # Extract all p caption elements
                    [s.extract() for s in soup.find_all("p.IMG---Figure")]

                    # Save the modified HTML back to the file
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(str(soup))

        # Create a new EPUB file with the modified content
        with zipfile.ZipFile(output_path, "w") as new_epub:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    new_epub.write(file_path, arcname)
    except Exception as e:
        logger.warning(f"Error processing image {img_path}: {e}")
        logger.warning(traceback.format_exc())
    # Clean up temporary directory
    shutil.rmtree(temp_dir)

def epubExtension(fullFileName):
    if len(fullFileName) < 6 or fullFileName[-5:] != ".epub":
        raise argparse.ArgumentTypeError("invalid file: the extension has to be epub")
    return fullFileName

def main():
    logging.basicConfig(level=logging.INFO)
    config_path = get_app_config_dir() / "config.ini"
    if not os.path.exists(config_path):
        print(f"File {config_path} does not exist.")
        sys.stdout.flush()
        sys.exit(1)
    config = configparser.ConfigParser()
    config.read(config_path)
    configSections = config.sections()

    parser = argparse.ArgumentParser(
        prog="epub-optimizer",
        description="Optimize epub for a given device",
        epilog="epub-optimizer help",
    )
    parser.add_argument("input_file", nargs=1, type=epubExtension, help="input file is the first positional argument and it is mandatory")  # positional argument
    parser.add_argument("-D", "--output-dir", nargs='?', help="The output directory of the produced epub")  # positional argument
    group = parser.add_mutually_exclusive_group()
    group.add_argument("output_file", nargs='?', help="output file is optional, you can instead provide --output-suffix (not both)")  # positional argument
    #output_suffix
    group.add_argument("-s", "--output-suffix", nargs = '?', default = "optimized", help="output suffix is optional you can instead provide a second positional argument as output file name (not both)")
    device = None
    if (len(configSections) > 1):
        parser.add_argument("-d", "--device", nargs=1, choices=configSections)
    else:
        device = [configSections[0]]
    args = parser.parse_args(sys.argv[1:])
    output_file = None
    if args.output_file == None:
        input_file_name = args.input_file[0][:-5].split("/")[-1] 
        output_file = f"{input_file_name}-{args.output_suffix}.epub"
    else: 
        output_file = args.output_file
        if args.output_dir is None and args.input_file[0] == output_file.lower():
            print("Error: input file and output file must be different (case-insensitive).")
            sys.stdout.flush()
            sys.exit(1)
        if args.output_dir is not None and "/" in output_file:
            print("Error: if output directory is specified, output file has not to contain any path but just the desired file name.")
            sys.stdout.flush()
            sys.exit(1)
    if args.output_dir is not None:
        output_file = (args.output_dir + "/" + output_file).replace("//","/")
    if os.path.exists(output_file):
        print(f"File {output_file} already exists.")
        sys.stdout.flush()
        sys.exit(1)
    if device is None:
        device = args.device
    [width, height] = map(lambda s: int(s), config[device[0]]['resolution'].lower().split("x"))
    print(f"input={args.input_file[0]} | output={output_file} | device={device} | res={width}x{height}")

    modify_img_tags(args.input_file[0], output_file, width, height)
    print(f"Modified EPUB saved to {output_file}")

if __name__ == '__main__':
    main()