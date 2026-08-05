from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from backend.channel_lookup import lookup_channel_candidates
from backend.database import SessionLocal, engine
from backend.models import Channel


FREQUENCY_QUANTUM = Decimal("0.000001")


def to_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None

    return Decimal(str(value)).quantize(FREQUENCY_QUANTUM)


def choose_matching_candidate(channel: Channel):
    candidates = lookup_channel_candidates(
        channel.input_mode,
        channel.input_fcn,
    )

    exact_matches = [
        candidate
        for candidate in candidates
        if candidate["band"] == channel.band
        and candidate["mode"] == channel.mode
        and candidate["fcn_dl"] == channel.fcn_dl
        and candidate["fcn_ul"] == channel.fcn_ul
    ]

    if len(exact_matches) == 1:
        return exact_matches[0]

    relaxed_matches = [
        candidate
        for candidate in candidates
        if candidate["band"] == channel.band
        and candidate["mode"] == channel.mode
    ]

    if len(relaxed_matches) == 1:
        return relaxed_matches[0]

    return None


def main() -> None:
    backup_table = (
        "channels_backup_precision_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    print(f"Membuat backup tabel: {backup_table}")

    with engine.begin() as connection:
        connection.execute(
            text(f"CREATE TABLE `{backup_table}` LIKE channels")
        )
        connection.execute(
            text(
                f"INSERT INTO `{backup_table}` "
                "SELECT * FROM channels"
            )
        )

    print("Backup tabel berhasil dibuat.")
    print("Mengubah kolom frekuensi menjadi DECIMAL(12,6)...")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                ALTER TABLE channels
                    MODIFY freq_dl_mhz DECIMAL(12,6) NULL,
                    MODIFY freq_ul_mhz DECIMAL(12,6) NULL
                """
            )
        )

    print("Struktur kolom berhasil diperbarui.")

    db = SessionLocal()
    updated_count = 0
    skipped_count = 0

    try:
        channels = db.query(Channel).order_by(Channel.id.asc()).all()

        for channel in channels:
            candidate = choose_matching_candidate(channel)

            if candidate is None:
                skipped_count += 1
                print(
                    f"SKIP channel id={channel.id} "
                    f"({channel.channel_number}): kandidat tidak unik."
                )
                continue

            channel.freq_dl_mhz = to_decimal(
                candidate["freq_dl_mhz"]
            )
            channel.freq_ul_mhz = to_decimal(
                candidate["freq_ul_mhz"]
            )
            channel.fcn_dl = candidate["fcn_dl"]
            channel.fcn_ul = candidate["fcn_ul"]
            channel.band = candidate["band"]
            channel.mode = candidate["mode"]
            updated_count += 1

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    print(f"Channel diperbaiki: {updated_count}")
    print(f"Channel dilewati : {skipped_count}")

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    channel_number,
                    CAST(freq_dl_mhz AS CHAR) AS freq_dl_mhz,
                    CAST(freq_ul_mhz AS CHAR) AS freq_ul_mhz
                FROM channels
                ORDER BY id
                """
            )
        ).fetchall()

    print("Nilai frekuensi setelah migrasi:")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
