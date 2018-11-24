#
# Utility functions are written here.
#
import struct
import hashlib
import socket
import time

DEFAULT_STP_MAX_BYTES = 40 # The maximum amount of data a STP packet can hold.
DEBUG = False

start_time = 0

sender_log_file_summary = {
    "file_size": 0,
    "seg_transmitted": 0,
    "seg_pld_messed": 0,
    "seg_dropped": 0,
    "seg_corrupted": 0,
    "seg_reorder": 0,
    "seg_dupped": 0,
    "seg_delayed": 0,
    "retrans_timeout": 0,
    "retrans_fast": 0,
    "dup_acks": 0
}

receiver_log_file_summary = {
    "data_received": 0,
    "segments_received_total": 0,
    "segments_received": 0,
    "segments_corrupt": 0,
    "segments_duplicate": 0,
    "duplicate_ack_sent": 0
}

def isstrint(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


class STPPacket:
    # ================================================================================
    # CONSTRUCTOR
    # ================================================================================
    def __init__(self, stp_max_bytes=DEFAULT_STP_MAX_BYTES, source_address="127.0.0.1", dest_address="127.0.0.1"):
        # This is where we define the STP header data
        self.source_address = source_address
        self.dest_address = dest_address
        self.sequence_num = 0
        self.acknowledge_num = 0
        self.window_size = 0
        self.syn = False
        self.ack = False
        self.fin = False
        self.checksum = 0

        # This will hold the data to send. We can only send STP_MAX_BYTES bytes at max
        self.payload = bytearray(0)

        # This is the raw byte data of the header
        self.raw = None

        self.assemble_format = '!LLLBBBxQ'

    def reset_flags(self):
        self.syn = False
        self.ack = False
        self.fin = False

    def assemble_stp_header(self):
        # Assemble all of the information into the byte data but we are keeping the checksum 0 so we can check for
        # corruption
        self.raw = socket.inet_aton(self.source_address)
        self.raw = self.raw + socket.inet_aton(self.dest_address)

        other_raw_data = struct.pack(
            self.assemble_format,
            self.sequence_num,
            self.acknowledge_num,
            self.window_size,
            self.syn,
            self.ack,
            self.fin,
            0
        )
        self.raw = self.raw + other_raw_data + self.payload

        self.calculate_checksum()

    def calculate_checksum(self):
        # Using the blake2b hash library to compute an 8 byte hash as the checksum, we will then reassemble the
        # header with this checksum
        h = hashlib.blake2b(digest_size=4)
        h.update(self.raw)
        self.checksum = int.from_bytes(h.digest(), byteorder='little')

        self.raw = socket.inet_aton(self.source_address)
        self.raw = self.raw + socket.inet_aton(self.dest_address)
        other_raw_data = struct.pack(
            self.assemble_format,
            self.sequence_num,
            self.acknowledge_num,
            self.window_size,
            self.syn,
            self.ack,
            self.fin,
            self.checksum
        )
        self.raw = self.raw + other_raw_data + self.payload

    def break_raw_data(self, data):
        retrieved_data = struct.unpack(self.assemble_format, data[8:32])

        # We are going to get the information from the data and set this STP packet to contain this information
        # After wards, we are going to assemble the STP header again, calculate the checksum and compare it to the
        # checksum we got from the stream.
        self.source_address = socket.inet_ntoa(data[:4])
        self.dest_address = socket.inet_ntoa(data[4:8])
        self.sequence_num = retrieved_data[0]
        self.acknowledge_num = retrieved_data[1]
        self.window_size = retrieved_data[2]
        self.syn = retrieved_data[3]
        self.ack = retrieved_data[4]
        self.fin = retrieved_data[5]
        retrieved_checksum = retrieved_data[6]

        self.payload = data[32:]

        # We are now going to check if the header was broken
        self.assemble_stp_header()

        if self.checksum != retrieved_checksum:
            return False
        return True

    def load_payload(self, byte_data):
        max_bytes = len(self.payload)

        counter = 0
        for byte in byte_data:
            if counter == max_bytes:
                break
            self.payload[counter] = byte
            counter = counter + 1


def copy_stp_packet(source, dest):
    dest.source_address = source.source_address
    dest.dest_address = source.dest_address
    dest.acknowledge_num = source.acknowledge_num
    dest.sequence_num = source.sequence_num
    dest.window_size = source.window_size
    dest.syn = source.syn
    dest.ack = source.ack
    dest.fin = source.fin
    dest.checksum = source.checksum
    dest.payload = source.payload
    dest.raw = source.raw


def create_log_file(output_file):
    output_file.write("|{:^9}|{:^10}|{:^13}|{:^9}|{:^12}|{:^9}|\n"
                .format("EVENT", "TIME", "PACK TYPE", "SEQ NUM", "DATA BYTES", "ACK NUM"))


def write_log(event, stp_packet, output_file):
    # Store the current time so the following commands don't distort the time
    current_time = time.time()
    packet_type = ""

    if stp_packet.syn:
        packet_type += "SYN"

    if stp_packet.ack:
        if len(packet_type) > 0:
            packet_type += "/"
        packet_type += "ACK"

    if stp_packet.fin:
        if len(packet_type) > 0:
            packet_type += "/"
        packet_type += "FIN"

    if len(stp_packet.payload) > 0:
        if len(packet_type) > 0:
            packet_type += "/"
        packet_type += "DATA"

    output_file.write("|{:^9}|{:^10}|{:^13}|{:^9}|{:^12}|{:^9}|\n"
                .format(event,
                    str(current_time - start_time)[0:10],
                    packet_type,
                    stp_packet.sequence_num,
                    len(stp_packet.payload),
                    stp_packet.acknowledge_num
                )
            )


def write_sender_summary(output_file):
    str_format = "{:60} {:>10}\n"
    output_file.write("=======================================================================\n")
    output_file.write(str_format.format("Size of the file (in Bytes)", sender_log_file_summary["file_size"]))
    output_file.write(str_format.format(
        "Segments transmitted (including drop & RXT)", sender_log_file_summary["seg_transmitted"]))
    output_file.write(str_format.format("Number of Segments handled by PLD", sender_log_file_summary["seg_pld_messed"]))
    output_file.write(str_format.format("Number of Segments dropped", sender_log_file_summary["seg_dropped"]))
    output_file.write(str_format.format("Number of Segments Corrupted", sender_log_file_summary["seg_corrupted"]))
    output_file.write(str_format.format("Number of Segments Re-ordered", sender_log_file_summary["seg_reorder"]))
    output_file.write(str_format.format("Number of Segments Duplicated", sender_log_file_summary["seg_dupped"]))
    output_file.write(str_format.format("Number of Segments Delayed", sender_log_file_summary["seg_delayed"]))
    output_file.write(str_format.format(
        "Number of Retransmissions due to TIMEOUT", sender_log_file_summary["retrans_timeout"]))
    output_file.write(str_format.format("Number of FAST RETRANSMISSION", sender_log_file_summary["retrans_fast"]))
    output_file.write(str_format.format("Number of DUP ACKS received", sender_log_file_summary["dup_acks"]))
    output_file.write("=======================================================================\n")


def write_receiver_summary(output_file):
    str_format = "{:60} {:>10}\n"
    output_file.write("=======================================================================\n")
    output_file.write(str_format.format("Amount of data received (bytes)", receiver_log_file_summary["data_received"]))
    output_file.write(str_format.format("Total Segments Received",
                                        receiver_log_file_summary["segments_received_total"]))
    output_file.write(str_format.format("Data segments received", receiver_log_file_summary["segments_received"]))
    output_file.write(str_format.format("Data segments with Bit Errors", receiver_log_file_summary["segments_corrupt"]))
    output_file.write(str_format.format("Duplicate data segments received",
                                        receiver_log_file_summary["segments_duplicate"]))
    output_file.write(str_format.format("Duplicate ACKs sent", receiver_log_file_summary["duplicate_ack_sent"]))
    output_file.write("=======================================================================\n")
