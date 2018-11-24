from colorama import Fore
from colorama import Style
from colorama import init
import utility
import sys
import socket
import time
import PLDModule

init()

if not len(sys.argv) == 15:
    print('Incorrect parameters. You need 14.')
    exit()

# ------------------------------------------
# Set up the receiver information.
RECEIVER_IP = sys.argv[1]
RECEIVER_PORT = int(sys.argv[2])
FILE_TO_TRANSMIT = sys.argv[3]
MAX_WIN_SIZE = int(sys.argv[4])
MAX_SEG_SIZE = int(sys.argv[5])
GAMMA = float(sys.argv[6])  # Assist in calculating the timeout

PLD = PLDModule.PLDModule()
PLD.probability_drop = float(sys.argv[7])
PLD.probability_duplicate = float(sys.argv[8])
PLD.probability_corrupt = float(sys.argv[9])
PLD.probability_reorder = float(sys.argv[10])
PLD.reorder_max_delay = float(sys.argv[11])
PLD.probability_delay = float(sys.argv[12])
PLD.delay_max_delay = float(sys.argv[13])/1000

PLDModule.set_random_seed(float(sys.argv[14]))

# Preset variables
ALPHA = 0.125
BETA = 0.25
FAST_RETRANSMIT_THRESHOLD = 3
MAX_TIMEOUT = 60
MIN_TIMEOUT = 1

estimated_rtt = 0.500
deviation_rtt = 0.250

sender_file_handler = open("Sender_log.txt", 'w')
PLD.file_writer = sender_file_handler
utility.create_log_file(sender_file_handler)
utility.start_time = time.time()

# Load the file data
with open(FILE_TO_TRANSMIT, 'rb') as f:
    all_file_bytes = f.read()
    utility.sender_log_file_summary["file_size"] = len(all_file_bytes)

# =============================================
# LETS GO! LETS GET THE BALL ROLLING
# =============================================
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
PLD.linked_socket = sock

# This is to send the syn connection packet (Initialise STP)
SendingPacket = utility.STPPacket()
SendingPacket.syn = True
SendingPacket.sequence_num = 0
SendingPacket.window_size = MAX_WIN_SIZE
SendingPacket.assemble_stp_header()

sock.sendto(SendingPacket.raw, (RECEIVER_IP, RECEIVER_PORT))
SendingPacket.sequence_num = SendingPacket.sequence_num + 1

utility.write_log("snd", SendingPacket, sender_file_handler)
utility.sender_log_file_summary["seg_transmitted"] += 1

remaining_window_space = MAX_WIN_SIZE
sender_receiving = True
ReceivedPacket = utility.STPPacket()

while sender_receiving:
    # Trying to receive data that the server acknowledges the client's packet
    print("Sender is now waiting for an ACK reply from the server.")
    data, address = sock.recvfrom(1024)
    if ReceivedPacket.break_raw_data(data):
        if ReceivedPacket.ack:
            utility.write_log("rcv", ReceivedPacket, sender_file_handler)
            SendingPacket.reset_flags()
            SendingPacket.ack = True
            SendingPacket.acknowledge_num = ReceivedPacket.sequence_num + 1
            SendingPacket.assemble_stp_header()

            # Send a packet to tell the server we received their acknowledgement packet
            sock.sendto(SendingPacket.raw, (RECEIVER_IP, RECEIVER_PORT))
            utility.write_log("snd", SendingPacket, sender_file_handler)
            utility.sender_log_file_summary["seg_transmitted"] += 1
        else:
            # Junk packet, ignore. This should not happen in this assignment as per the rules.
            continue
    else:
        # Read comment 3 lines above.
        print("Received packet was corrupted.")
        continue

    # ----------------------------------------------
    # Connection established, time to send our data.

    # NOTE TO SELF: PACKET_INDEX will refer to the index of the bytes in the all_file_bytes data. While oldest_index
    # and all off the acknowledgement & sequence numbers will be based off their own index. Hence, make sure when
    # converting any of the ack/seq/oldest index, subtract it with the starting_bias variable.
    # VERY IMPORTANT
    starting_bias = SendingPacket.sequence_num
    packet_index = 0
    oldest_flag = True
    oldest_index = SendingPacket.sequence_num
    oldest_time = 0
    start_rtt_flag = True
    rtt_time = 0
    record_rtt = True

    informed_user = False

    retransmit_index = 0
    retransmit_num = 0
    retransmitting = False
    while True:
        # Calculate the timeout time here
        timeout_time = estimated_rtt + GAMMA * deviation_rtt
        if timeout_time > MAX_TIMEOUT:
            timeout_time = MAX_TIMEOUT
        if timeout_time < MIN_TIMEOUT:
            timeout_time = MIN_TIMEOUT
        # print("Timeout time is given as: {}".format(timeout_time))

        send_start = packet_index
        send_end = send_start + MAX_SEG_SIZE
        if send_end > len(all_file_bytes):
            send_end = len(all_file_bytes)

        file_bytes = all_file_bytes[send_start:send_end]

        if remaining_window_space >= len(file_bytes) != 0:
            print("We are going to send bytes from {} to {}.".format(send_start, send_end))
            print("Sequence number: {}".format(SendingPacket.sequence_num))
            # We still have space to send packets. Send it through.
            SendingPacket.reset_flags()
            SendingPacket.payload = file_bytes
            SendingPacket.assemble_stp_header()

            PLD.send_data(SendingPacket, RECEIVER_IP, RECEIVER_PORT, retransmitting)
            utility.sender_log_file_summary["seg_transmitted"] += 1

            if retransmitting:
                retransmitting = False
                record_rtt = False

            # If this is the first packet to be sent in the window, remember by the sequence number the data
            # started at.
            if oldest_flag:
                oldest_flag = False
                oldest_time = time.time()
                record_rtt = True
                start_rtt_flag = True

            if start_rtt_flag:
                start_rtt_flag = False
                rtt_time = time.time()

            # Prepare the next packet's reserved space.
            SendingPacket.sequence_num = SendingPacket.sequence_num + len(file_bytes)

            remaining_window_space -= len(file_bytes)
            packet_index += len(file_bytes)

            print(Fore.CYAN + "We have {} bytes left in the window.\n".format(remaining_window_space) + Style.RESET_ALL)
        else:
            # We ran out of space, time to wait for the server to send the ACK
            if len(file_bytes) > 0:
                if not informed_user:
                    print(Fore.YELLOW + "Ran out of window space. Wait for server's ACKs." + Style.RESET_ALL)
                    informed_user = True
            else:
                if not informed_user:
                    print(Fore.YELLOW + "Finished sending data. Waiting to verify arrival of data." + Style.RESET_ALL)
                    informed_user = True
                # The oldest index has matched the sequence number of the most recently sent packet. This means
                # we just have confirmed that we sent the data packets. Commence termination.
                if SendingPacket.sequence_num == oldest_index:
                    print(Fore.GREEN + "All data received. Stopping ..." + Style.RESET_ALL)
                    break

            sock.settimeout(0)  # Turn on Non-blocking mode for the timer.
            try:
                data, address = sock.recvfrom(1024)  # Buffer size of 1024 bytes
            except BlockingIOError:
                if (time.time() - oldest_time) > timeout_time:
                    # We timed out, resend the packet that the server is expecting.
                    print(Fore.LIGHTRED_EX + "Timed out, unable to establish a connection." + Style.RESET_ALL)
                    remaining_window_space = packet_index - (oldest_index - starting_bias)
                    packet_index = ReceivedPacket.acknowledge_num - starting_bias
                    oldest_index = ReceivedPacket.acknowledge_num
                    oldest_flag = True
                    SendingPacket.sequence_num = ReceivedPacket.acknowledge_num
                    utility.sender_log_file_summary["retrans_timeout"] += 1
                    retransmitting = True
                continue

            informed_user = False

            if ReceivedPacket.break_raw_data(data):
                # We received a packet, check it against the oldest index. We will only process the packet if it is
                # younger than the oldest index on record. By doing this, if one of the packets is lost midway, we
                # still are able to proceed.
                if ReceivedPacket.acknowledge_num > oldest_index:
                    utility.write_log("rcv", ReceivedPacket, sender_file_handler)
                    retransmit_num = 0
                    retransmit_index = ReceivedPacket.acknowledge_num
                    if len(file_bytes) > 0:
                        sample_rtt = time.time() - rtt_time
                        print(Fore.GREEN +
                              "Received acknowledgement of, {}".format(ReceivedPacket.acknowledge_num) +
                              Style.RESET_ALL +
                              " | " +
                              Fore.LIGHTGREEN_EX + "RTT of: {}".format(sample_rtt) + Style.RESET_ALL)
                        if record_rtt:
                            estimated_rtt = (1 - ALPHA) * estimated_rtt + ALPHA * sample_rtt
                            deviation_rtt = (1 - BETA) * deviation_rtt + BETA * abs(sample_rtt - estimated_rtt)
                            print("Using the RTT for timeout calculations.")
                        record_rtt = True
                    else:
                        print(Fore.GREEN +
                              "Received acknowledgement of, {}".format(ReceivedPacket.acknowledge_num) +
                              Style.RESET_ALL)
                    # Now that we received an acknowledgement, slide the window space up
                    remaining_window_space += ReceivedPacket.acknowledge_num - oldest_index
                    # Since we received an ACK and we slide the window up.
                    oldest_index = ReceivedPacket.acknowledge_num
                    oldest_flag = True
                    start_rtt_flag = True
                else:
                    print(Fore.RED +
                          "Received old packet with acknowledge of, {}. Ignore."
                          .format(ReceivedPacket.acknowledge_num) +
                          Style.RESET_ALL)
                    if retransmit_index == ReceivedPacket.acknowledge_num:
                        utility.write_log("rcv/DA", ReceivedPacket, sender_file_handler)
                        utility.sender_log_file_summary["dup_acks"] += 1
                        retransmit_num += 1
                        if retransmit_num >= FAST_RETRANSMIT_THRESHOLD:
                            print(Fore.LIGHTRED_EX +
                                  "Looks like we need to retransmit, {}."
                                  .format(ReceivedPacket.acknowledge_num) +
                                  Style.RESET_ALL)
                            # We have hit the fast retransmit threshold, go back to this acknowledge number and start
                            # resending the packets.
                            fast_retrans_start = ReceivedPacket.acknowledge_num - starting_bias
                            fast_retrans_end = fast_retrans_start + MAX_SEG_SIZE
                            if fast_retrans_end > len(all_file_bytes):
                                fast_retrans_end = len(all_file_bytes)

                            FastRetransPacket = utility.STPPacket()
                            FastRetransPacket.sequence_num = ReceivedPacket.acknowledge_num
                            FastRetransPacket.acknowledge_num = ReceivedPacket.sequence_num
                            FastRetransPacket.payload = all_file_bytes[fast_retrans_start:fast_retrans_end]
                            FastRetransPacket.assemble_stp_header()
                            PLD.send_data(FastRetransPacket, RECEIVER_IP, RECEIVER_PORT, True)
                            utility.sender_log_file_summary["retrans_fast"] += 1
                            utility.sender_log_file_summary["seg_transmitted"] += 1
                            retransmit_num = 0
                    else:
                        retransmit_num = 0
                        retransmit_index = ReceivedPacket.acknowledge_num
                        utility.write_log("rcv", ReceivedPacket, sender_file_handler)
            else:
                print("Received ACK packet was corrupted. Trying again ...")

    # --------------------------------------------------------
    # We finished sending the file, now to close it
    # Set to blocking for the closing handshake. We no longer need to maintain the timer ourselves.
    sock.settimeout(None)  # Turn on blocking mode
    print("Closing the connection.")
    SendingPacket.reset_flags()
    SendingPacket.fin = True
    SendingPacket.payload = bytearray(0)
    SendingPacket.assemble_stp_header()
    sock.sendto(SendingPacket.raw, (RECEIVER_IP, RECEIVER_PORT))

    utility.write_log("snd", SendingPacket, sender_file_handler)
    utility.sender_log_file_summary["seg_transmitted"] += 1

    SendingPacket.sequence_num += 1

    while True:
        # Wait for the server ACK
        data, address = sock.recvfrom(1024)

        if ReceivedPacket.break_raw_data(data):
            utility.write_log("rcv", ReceivedPacket, sender_file_handler)
            print("Received acknowledgement of, {}".format(ReceivedPacket.acknowledge_num))
            if ReceivedPacket.acknowledge_num == SendingPacket.sequence_num:
                break
            else:
                print(Fore.RED +
                      "Received acknowledgement of, {}. Not in sync, discard.".format(ReceivedPacket.acknowledge_num) +
                      Style.RESET_ALL)
        else:
            print("Received ACK packet was corrupted. Trying again ...")

    # Wait for the server FIN
    data, address = sock.recvfrom(1024)

    if ReceivedPacket.break_raw_data(data):
        utility.write_log("rcv", ReceivedPacket, sender_file_handler)

    # Send the ACK back and then wait for a while (double maximum segment life) in case our ACK was lost
    SendingPacket.reset_flags()
    SendingPacket.ack = True
    # We are adding one byte to the acknowledge number as the FIN flag consumes 1 byte
    SendingPacket.acknowledge_num = ReceivedPacket.sequence_num + 1
    SendingPacket.assemble_stp_header()

    sock.sendto(SendingPacket.raw, (RECEIVER_IP, RECEIVER_PORT))

    utility.write_log("snd", SendingPacket, sender_file_handler)
    utility.sender_log_file_summary["seg_transmitted"] += 1

    sock.close()

    print("Connection successfully closed.")
    utility.write_sender_summary(sender_file_handler)
    sender_file_handler.close()
    break
