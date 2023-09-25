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


## Inline Comments from Code Files

### pro-gcp-ocr.py

- # Configuración de las credenciales de GCP
- # Argumentos desde la línea de comando
- # Importing required libraries
- # Setting up the Google Cloud Platform credentials
- # Command line arguments setup
- # Initialize Vision client
- # File directories
- # Create output directory if it doesn't exist
- # Load JSON configurations
- # Function to process images and generate text files
- # Iterate over each image in the input folder
- # Process only jpg and png images
- # Process the image only if its corresponding text file doesn't exist
- # Open the image file
- # Use the Vision API to detect text in the image
- # Extract the detected text
- # Write the extracted text to a file
- # Call the function to process images
- # Inicializa el cliente de Vision
- # Directorios de archivos
- # Crea el directorio de salida si no existe
- # Cargar configuraciones de JSON
- # Función para procesar imágenes y generar archivos de texto
- # Llamada a la función para procesar imágenes

### pre-pdf.py

- # Importing required libraries
- # Function to split pages from a PDF and save as text files
- # Open the PDF file
- # If no specific pages are provided, process all pages
- # Loop through each page
- # Extract text from the page
- # text.replace("", "")
- # Construct the output file path
- # Write the extracted text to the output file
- # Function to convert pages from a PDF to images
- # Open the PDF document
- # If no specific pages are provided, process all pages
- # Loop through each page
- # Convert the page to an image
- # Save the image to the output folder
- # Function to parse the pages argument
- # If a range of pages is provided
- # If specific pages are provided
- # Main function to handle command line arguments and call the appropriate function
- # Add command line arguments for the pages, PDF file path, output folder, and mode
- # Parse the command line arguments
- # Check if the mode is valid
- # Parse the pages argument if provided
- # Create the output folder if it doesn't exist
- # Call the appropriate function based on the mode

### pre-cleanup.py

- # Importing required libraries
- # Function to process all text files in a directory
- # Loop through each file in the directory
- # Check if the file is a text file
- # Construct the full filepath
- # Open and read the file
- # Use BeautifulSoup to clean up HTML tags in the text
- # Use NLTK for sentence tokenization
- # Combine sentences with two line breaks for new paragraphs
- # Various text clean-up operations for TTS
- # Remove hyphens between words
- # Replace multiple spaces with a single space
- # Remove space before commas
- # Replace '&' with 'and'
- # Write the cleaned up text back to the file
- # Print a success message when all files have been processed
- # Print an error message if something goes wrong
- # Main function to handle command line arguments and call the processing function
- # Add a command line argument for the directory path
- # Parse the command line arguments
- # Call the processing function with the directory path argument

### pro-gcp-tts.py

- # Importing required libraries
- # Setting up the Google Cloud Platform credentials
- # Command line arguments setup
- # Initialize Text-to-Speech client
- # File directories
- # Create output folder if it does not exist
- # Load JSON configurations
- # Function to split text into parts of maximum size max_bytes
- # Function to generate audio from a text file
- # Iterate over each part of the text
- # Skip the part if its corresponding audio file already exists
- # Set up the input text, voice and audio configuration for the Text-to-Speech API
- # Use the Text-to-Speech API to synthesize speech
- # Write the synthesized speech to an audio file
- # Function to generate audio from all text files in the input folder
- # Run the function to generate audio


## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License
This project is licensed under the MIT License.
