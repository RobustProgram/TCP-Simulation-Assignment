import random
import utility
import threading


def set_random_seed(seed):
    random.seed(seed)


class PLDModule:
    def __init__(self):
        self.probability_drop = 0
        self.probability_duplicate = 0
        self.probability_corrupt = 0
        self.probability_reorder = 0
        self.probability_delay = 0
        self.reorder_max_delay = 0
        self.delay_max_delay = 0

        self.linked_socket = None
        self.file_writer = None

        self.reorder_segment_wait = 0
        self.reorder_segment = None

    def send_delayed_data(self, stp_packet, receiver_ip, receiver_port):
        try:
            self.linked_socket.sendto(stp_packet.raw, (receiver_ip, receiver_port))
            utility.write_log("snd/delay", stp_packet, self.file_writer)
        except OSError:
            # The socket is closed and we are trying to call it. Just ignore it  # ¯\_(ツ)_/¯
            pass

    def send_data(self, stp_packet, receiver_ip, receiver_port, retranmission=False):
        if self.linked_socket is not None:
            data = stp_packet.raw
            rand_num = random.random()
            event_log = ""

            if rand_num < self.probability_drop:
                utility.write_log("drop", stp_packet, self.file_writer)
                utility.sender_log_file_summary["seg_dropped"] += 1
                utility.sender_log_file_summary["seg_pld_messed"] += 1
                return
            else:
                rand_num = random.random()

            if rand_num < self.probability_duplicate:
                self.linked_socket.sendto(data, (receiver_ip, receiver_port))
                utility.sender_log_file_summary["seg_transmitted"] += 1
                utility.sender_log_file_summary["seg_pld_messed"] += 1

                if retranmission:
                    utility.write_log("snd/RXT", stp_packet, self.file_writer)
                    event_log = "snd/RXT/dup"
                else:
                    utility.write_log("snd", stp_packet, self.file_writer)
                    event_log = "snd/dup"

                utility.sender_log_file_summary["seg_dupped"] += 1
                rand_num = 1
            else:
                rand_num = random.random()

            if rand_num < self.probability_corrupt:
                data_byte_array = bytearray(data)
                data_byte_array[6] = data_byte_array[6] ^ 101  # ¯\_(ツ)_/¯
                data = bytes(data_byte_array)
                if retranmission:
                    event_log = "snd/RXT/corr"
                else:
                    event_log = "snd/corr"
                utility.sender_log_file_summary["seg_corrupted"] += 1
                rand_num = 1
            else:
                rand_num = random.random()

            if rand_num < self.probability_reorder and self.reorder_segment is None:
                self.reorder_segment = utility.STPPacket()
                utility.copy_stp_packet(stp_packet, self.reorder_segment)
                return
            else:
                rand_num = random.random()

            if rand_num < self.probability_delay:
                # We will need to duplicate the packet to delay.
                delay_segment = utility.STPPacket()
                utility.copy_stp_packet(stp_packet, delay_segment)

                delay_time = random.random() * self.delay_max_delay
                delay_thread = threading.Timer(delay_time, self.send_delayed_data,
                                               [delay_segment, receiver_ip, receiver_port])
                delay_thread.start()

                utility.sender_log_file_summary["seg_delayed"] += 1
                utility.sender_log_file_summary["seg_pld_messed"] += 1
                return
            else:
                rand_num = random.random()

            if rand_num != 1:
                if retranmission:
                    event_log = "snd/RXT"
                else:
                    event_log = "snd"

            self.linked_socket.sendto(data, (receiver_ip, receiver_port))
            utility.write_log(event_log, stp_packet, self.file_writer)

            if self.reorder_segment is not None:
                self.reorder_segment_wait += 1

                if self.reorder_segment_wait >= self.reorder_max_delay:
                    self.linked_socket.sendto(self.reorder_segment.raw, (receiver_ip, receiver_port))
                    utility.write_log("snd/delay", self.reorder_segment, self.file_writer)
                    self.reorder_segment = None
                    self.reorder_segment_wait = 0
                    utility.sender_log_file_summary["seg_reorder"] += 1
                    utility.sender_log_file_summary["seg_pld_messed"] += 1

            utility.sender_log_file_summary["seg_pld_messed"] += 1

        else:
            print("You need to link the PLD Module with a socket before we can do anything.")
