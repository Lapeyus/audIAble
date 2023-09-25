# Google Text-to-Speech Audio Generator

## Overview
This script converts text files to audio using Google's Text-to-Speech API. It takes text files from an input folder and saves the generated audio files into an output folder. The script is configurable, allowing you to specify the voice, audio encoding, and other features for the generated audio.

## Requirements
- Python 3.x
- Google Cloud Platform account
- Google Cloud Text-to-Speech API credentials
- `google-cloud-texttospeech` Python package

## Installation
Install the required Python package by running:
```bash
pip install google-cloud-texttospeech
```

## Configuration
1. Download your Google Cloud API JSON credential file.
2. Place your Google Cloud API JSON credential file in the project root and rename it to `credentials.json`.
3. Update the `config.json` file to set your desired voice and audio configurations.

## Usage
1. Place your text files into an input folder.
2. Run the script with the following command-line arguments:
    ```bash
    python script.py --f <path-to-folder-containing-text-files> --o <path-to-folder-to-save-generated-audio-files>
    ```
   - `--f`: Folder containing the text files to be processed.
   - `--o`: Folder to save the generated audio files.

For example:
```bash

python3 pre-pdf.py --f book.pdf --o ./cap1 --m split --p 19-43

python3 pre-pdf.py --f book.pdf --o ./cap1 --m photo --p 19-43

python3 pre-cleanup.py --f cap1/

python3 pro-gcp-ocr.py  --f cap1/img/ --o cap1/ocr

python3 pro-gcp-tts.py  --f cap1/ocr/ --o cap1/audio

```

## Features
- Command-line interface for easy execution.
- Ability to split large text into smaller parts to manage Text-to-Speech API limitations.
- Checks for existing audio files to avoid redundant processing.
- Audio properties like pitch and speed are customizable via the `config.json` file.

## Function Overview
- `dividir_texto()`: Splits text into smaller parts.
- `generar_txt_audio()`: Generates audio for a specific text file.
- `generar_audio()`: Driver function to process all text files in the input folder.

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License
This project is licensed under the MIT License.
