import os
import re
from datetime import datetime, timedelta, timezone

tz = timezone(timedelta(hours=7))

STUDIES = ['24EIb', '24EIc','39EIa','01NVb','01NVc']+\
	['05EI_Covid19', '05EI_MPox', '05EI_Flu'] +\
	['24EIB', '39EIA','54EI', '56EI', '47EI', '46EI', '05EI', '28EI', '00EI','24EIC', '08NV','09NV','17EI','39EI','01NVB','55EI', '01NVC','46EI','60EI','66DX', '60EI', '62EI'] +\
	['13NV', '61EI', '66EI']
	

PATTERN = [
	"\d{4}-\d{2}-\d{2}_\d{2}.\d{2}.\d{2}",  # iP
	"(\d{4}\d{2}\d{2}T\d{2}\d{2}\d{2}\.\d+\+\d{2}\d{2})",  # UTC
]
FORMAT = ["%Y-%m-%d_%H.%M.%S", "%Y%m%dT%H%M%S.%f%z"]  # iP  # UTC


def ISO_to_iP(x):
	if not x:
		return ""
	try:
		return datetime.fromisoformat(x).strftime("%d.%m.%Y.%H.%M.%S")
	except ValueError:
		return x


class FileNameParser:
	"""This class support parsing (like Folder in research_convention) for local files in INNOVATION/DataUploader"""

	def __init__(self, file) -> None:
		self.file = file

	def parse(self):
		study = self.get_study()
		patient = self.get_patient()
		datatype = self.get_datatype()
		start = self.get_start_time(datatype)
		end = self.get_end_time(datatype)
		device = self.get_device()
		filename = self.get_filename(datatype)
		duration=(end - start).total_seconds() if end and start else None
		size = self.get_size()
		date = self.get_date()
		parsed_info = {
			"study": study,
			"patient": patient,
			"datatype": datatype,
			"start": start.isoformat() if start else None,
			"end": end.isoformat() if end else None,
			"date": date.isoformat() if date else None,
			"device": device,
			"duration": duration,
			"filename": filename,
			"size": size,
			"path": self.file
		}
		return parsed_info

	def get_study(self):
		if self.file.find('Log_')!=-1:
			return None
		matches = re.findall(
			r"[DataUploader|mnt|Documents|__pycache__/DataUpload|DataUpload|.received]/(\d+\w+)/.*", self.file.replace("\\", "/")
		)
		if len(matches):
			valid = list(set(filter(lambda x: x.upper() in STUDIES, matches)))
			if len(valid):
				return valid[0]
		for i in STUDIES:
			if self.file.find(i) != -1:
				return i
		return None

	def get_datatype(self):
		if not self.file:
			return None
		path = self.file.lower()
		if re.search("(smartcare|ppg|pleth)", path):
			return "PPG"
		if re.search("(SmartCareCsv)", self.file):
			return "PPG"
		if re.search("(EcgCsv)", self.file):
			return "ECG"
		if re.search("(OCR_|Image_|Metadata_)", self.file):
			return "Image"
		if re.search('x-?ray', path):
			return "X-ray"
		if re.search("Annotation|Log_", self.file):
			return "Note"
		if re.search(
				"(shimmer|efs|ecg|edf|missing|chainfo|chaninfo|events|devperf|annot|\.rr)", path
		):
			return "ECG"
		if re.search("(ultrasound|/ult/|uls)", path):
			return "Ultrasound"
		if re.search('mri', path):
			return "MRI"
		if re.search("gyro", path):
			return "Gyro"
		if re.search("Nonin", self.file):
			return "PPG"
		if re.search("39EIa", self.file) and re.search("ULT", self.file):
			return "Ultrasound"
		if re.search("01NVb", self.file):
			return "Ultrasound"
		if re.search("01NVc", self.file):
			return "Ultrasound"
		if re.search("(ECG/.*_RST.xml)", self.file):
			return "sECG"
		if re.search("(nom|monitor|mp|trend|waves|drc|asc)", path):
			return "Monitor"
		if re.search(r'\d+\w+-\d+-\d+-?[a-zA-Z0-9]*\.txt', path):
			return "Monitor"
		if path.find('stream.txt')!=-1:
			return "Monitor"
		if re.search("(jpg|jpeg|png)", path):
			return "Image"
		if re.search("(mp3|wav)", path):
			return "Audio"
		if re.search("(BloodPressureCsv)", self.file):
			return "BloodPressure"
		if re.search("(USCOM)", self.file):
			return "USCOM"
		if re.search(r'\bCT\b', self.file) or re.search(r'\bCTScan\b', self.file):
			return "CTScan"
		return "Others"

	def get_start_time(self, datatype):
		file = self.file
		if file.find('Annotation')!=-1 or file.find('Log_')!=-1:
			matches = re.findall("\d{4}-\d{2}-\d{2}", file)
			if len(matches) > 0:
				return datetime.strptime(
					matches[0], "%Y-%m-%d"
				).replace(tzinfo=tz)

		if datatype in ["ECG","sECG"]:
			ts_format = {
				# shimmer consensys format
				'\d{4}-\d{2}-\d{2}_\d{2}.\d{2}.\d{2}': "%Y-%m-%d_%H.%M.%S",
				# Hospital ECG
				'[01]\d[0-3]\d20\d{2}_[0-2]\d[0-5]\d[0-5]\d': "%m%d%Y_%H%M%S",
			}
			for p, fmt in ts_format.items():
				matches = re.findall(p, file)
				if len(matches) > 0:
					try:
						return datetime.strptime(
							matches[0], fmt
						).replace(tzinfo=tz)
					except Exception as e:
						print('no date',file, 'due to', e)
		if datatype == "Gyro":
			return None
		if datatype == "PPG":
			for idx, p in enumerate(PATTERN):
				matches = re.findall(p, file)
				if len(matches) > 0:
					return datetime.strptime(
						matches[0], FORMAT[idx]
					).replace(tzinfo=tz)
		if file.find('28EI')!=-1:
			matches = re.findall("[0-3]\d[0-1]\d20[1-2]\d", file)
			if len(matches) > 0:
				try:
					return datetime.strptime(
						matches[0], "%d%m%Y"
					).replace(tzinfo=tz)
				except Exception as e:
					print('no date',file, 'due to', e)
			return None
		if file.find('39EIa')!=-1 and file.find('/ECG/')!=-1:
			# sECG
			matches = re.findall("[0-1]\d[0-3]\d20[1-2]\d", file)
			if len(matches) > 0:
				try:
					return datetime.strptime(
						matches[0], "%Y%m%d"
					).replace(tzinfo=tz)
				except Exception as e:
					print('no date',file, 'due to', e)
		if datatype == "X-ray":
			matches = re.findall("([0-3]\d[01]\d20\d{2})", file)
			if len(matches) > 0:
				try:
					return datetime.strptime(
						matches[0], "%d%m%Y"
					).replace(tzinfo=tz)
				except Exception as e:
					print('no date',file, 'due to', e)
			return None
		# Monitor and also wearable convention
		patterns = [
			("[0-3]\d.[0-1]\d.20[1-2]\d.[0-2]\d.[0-5]\d.[0-5]\d", "%d.%m.%Y.%H.%M.%S"),  #monitor
			("\d{14}",  "%Y%m%d%H%M%S"),  #YYYYMMDDHHMMSS
			("\d{12}",  "%Y%m%d%H%M")
		]
		for p, fmt in patterns:
			matches = re.findall(p, file)
			if len(matches) > 0:
				try:
					return datetime.strptime(
							matches[0], fmt
						).replace(tzinfo=tz)
				except Exception as e:
					print('no date',file, 'due to', e)
		return None
	def get_date(self):
		file = self.file
		# Define date formats and their patterns in priority order
		date_formats = [
			# Remove word boundaries (\b) to match dates in longer strings
			(r'([0-3]\d\.[01]\d\.20\d{2}\.[0-2]\d\.[0-5]\d\.[0-5]\d)', "%d.%m.%Y.%H.%M.%S"),  # 21.07.2025.11.05.06
			(r'(\d{2}[A-Za-z]{3}\d{2})', "%d%b%y"),                # 17OCT25
			(r'(\d{14})', "%Y%m%d%H%M%S"),                         # 20250721110529
			(r'(\d{8}T\d{6})', "%Y%m%dT%H%M%S"),                   # 20250721T110529
			(r'(20\d{2}[01]\d[0-3]\d)', "%Y%m%d"),                 # 20250721
			(r'([0-3]\d[01]\d20\d{2})', "%d%m%Y"),                 # 21072025
			(r'([0-3]\d\.[01]\d\.20\d{2})', "%d.%m.%Y"),           # 21.07.2025
			(r'(20\d{2}-[01]\d-[0-3]\d)', "%Y-%m-%d"),             # 2025-07-21
			(r'(\d{2}\d{2}\d{4}_\d{2}\d{2}\d{2})', "%m%d%Y_%H%M%S"),	 # 07212025_110529
		]
		
		# Try each pattern in priority order
		for pattern, date_format in date_formats:
			matches = re.findall(pattern, file)
			if matches:
				for match in matches:
					try:
						date_obj = datetime.strptime(match, date_format)
						return date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
					except Exception:
						continue
		return None


	def get_end_time(self, datatype):
		file = self.file
		if datatype == "ECG":
			matches = re.findall("\d{4}-\d{2}-\d{2}_\d{2}.\d{2}.\d{2}", file)
			if len(matches) > 1:
				return datetime.strptime(
					matches[1], "%Y-%m-%d_%H.%M.%S"
				).replace(tzinfo=tz)
		if datatype == "sECG":
			return None
		# Monitor and also wearable convention
		matches = re.findall("[0-3]\d.[0-1]\d.20[1-2]\d.[0-2]\d.[0-5]\d.[0-5]\d", file)
		if len(matches) > 1:
			try:
				return datetime.strptime(
					matches[1], "%d.%m.%Y.%H.%M.%S"
				).replace(tzinfo=tz)
			except Exception as e:
				print('no date',file, 'due to', e)

		return None

	def get_patient(self):
		file = self.file
		file = file.replace("01nvc", "01NVc")
		patterns = ["\d+\w+[_-]\d+[_-]\d+[_-][a-zA-Z]","\d+\w+[_-]\d+[_-]\d+", "\d+\w+[_-]\d+[_-]\d+-\d{1,2}"]
		for p in patterns:
			matches = re.findall(p, file)
			if len(matches) > 0:
				return matches[0].replace('_', '-')
		return None

	def get_device(self):
		file = self.file
		matches = re.findall("Shimmer_(\w+)_Calibrated_SD", file)
		if len(matches) > 0:
			return 'Shimmer'
		if file.endswith('.dcm') or file.split('/')[-1].find('.')==-1:
			return 'Not classified ULS Machine'
		if file.find('01NVc')!=-1:
			return 'Not classified ULS Machine'
		if re.search('/ULT/.*39EIa.*mp4',file) or re.search(r'Ultrasound|ULS',file):
			return 'Not classified ULS Machine'
		if file.endswith('.mp3') or file.upper().endswith('.WAV'):
			return 'SUNTECH recorder'
		for i in ['SmartCare','Shimmer', 'Nonin']:
			if file.find(i)!=-1:
				return i
		if re.search(r'smartcare', file.lower()):
			return 'SmartCare'
		if file.find('EcgCsv')!=-1:
			return 'VivaLNK'
		if file.find('BloodPressure')!=-1:
			return 'A&D BloodPressure'
		if file.find('NOM')!=-1 or re.search(r'\bMP',file):
			return 'Monitor Phillips'
		if file.find('.drc')!=-1 or file.find('.asc')!=-1 or file.find('STREAM.txt')!=-1:
			return 'Monitor GE'
		if re.search(r'EFS|edf|missing|chainfo|chaninfo|events|devperf|annot|\.rr', file):
			return 'ePatch'
		if re.search("ECG/.*_RST.xml", file):
			return 'Hospital ECG Machine'
		if re.search("Note", file):
			return 'Mobile App'
		if re.search("Gyro", file):
			return 'Axivity'
		if re.search(r'USCOM', file):
			return 'USCOM'
		if re.search(r'Metadata|Image|OCR|Log_', file):
			return 'Tablet'
		return None

	def get_filename(self, datatype):
		file = self.file
		if datatype == "Ultrasound":
			return file.split("/")[-1]
		if datatype in ["ECG", "sECG","PPG"]:
			return file.split("/")[-1]
		return file.split("/")[-1]
	def get_size(self):
		file = self.file
		try:
			return os.path.getsize(file)
		except:
			return None
	def rename_file(self, file_metadata):
		"""Rename file according to the metadata"""
		try:
			device = file_metadata['device']
			filename = file_metadata['filename']
			patient = file_metadata['patient']
			start = ISO_to_iP(file_metadata['start']) 
			end = ISO_to_iP(file_metadata['end'])
			ext = filename.rsplit('.', 1)[-1]
		except Exception as e:
			print('rename_file error', e)
			return filename
		if device in ['Monitor Phillips', 'Monitor GE']:
			if device=="Monitor Phillips":
				wave = filename.rsplit('.',1)[0].replace('_','-')
			elif device == 'Monitor GE':
				filename = filename.lower()
				wave = "trends" if filename.find('trend')!=-1 \
					else "waves" if filename.find('wave')!=-1 \
						else "stream" if filename.find('stream')!=-1 \
							else "alarms" if filename.find('alarm')!=-1 \
								else filename.rsplit('.',1)[-1]
			return f"{device.replace(' ','')}-{wave}_{patient}_{start}_{end}.{ext}"
		elif device == 'Shimmer':
			if filename.find('Calibrated_SD')!=-1:
				return f"ShimmerSD_{patient}_{start}_{end}.{ext}"
		return file_metadata['filename']


